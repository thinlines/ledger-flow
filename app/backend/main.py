from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import re
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from models import (
    ImportCandidateRemoveRequest,
    CustomImportAccountUpsertRequest,
    CreateAccountRequest,
    ImportPreviewRequest,
    ImportUndoRequest,
    ManualTransactionRequest,
    ManualTransferResolutionRequest,
    PayeeRuleRequest,
    RuleHistoryApplyRequest,
    RuleHistoryScanRequest,
    RuleCreateRequest,
    RuleReorderRequest,
    RuleUpdateRequest,
    StageApplyRequest,
    ToggleStatusRequest,
    TrackedAccountUpsertRequest,
    UnknownScanRequest,
    UnknownStageRequest,
    WorkspaceImportAccountUpsertRequest,
    WorkspaceBootstrapRequest,
    WorkspaceSelectRequest,
)
from services.backup_service import backup_file
from services.event_log_service import check_drift, check_startup_drift, emit_event, hash_file, rel_path
from services.header_parser import TransactionStatus, parse_header, set_header_status, HEADER_RE as _HEADER_RE
from services.account_register_service import build_account_register
from services.commodity_service import CommodityMismatchError
from services.custom_csv_service import inspect_csv_bytes
from services.activity_service import build_activity_view
from services.dashboard_service import build_dashboard_overview
from services.import_history_service import list_import_history, record_applied_import, undo_import
from services.import_index import ImportIndex
from services.import_service import (
    ImportPreviewBlockedError,
    apply_import,
    archive_inbox_csv,
    preview_import_safely,
    remove_inbox_csv,
    scan_candidates,
)
from services.manual_entry_service import create_manual_transaction
from services.manual_transfer_resolution_service import (
    apply_manual_transfer_resolution,
    preview_manual_transfer_resolution,
)
from services.import_profile_service import import_source_summary
from services.institution_registry import canonical_template_id, display_name_for, list_templates
from services.ledger_runner import CommandError, run_cmd
from services.opening_balance_service import OPENING_BALANCES_EQUITY, opening_balance_index
from services.rule_reapply_service import apply_rule_reapply, scan_rule_reapply
from services.stage_store import StageStore
from services.rules_service import (
    create_rule,
    delete_rule,
    ensure_rules_store,
    extract_set_account,
    load_rules,
    reorder_rules,
    update_rule,
    upsert_payee_rule,
)
from services.unknowns_service import (
    apply_unknown_mappings,
    create_account,
    list_category_accounts,
    list_known_accounts,
    scan_unknowns,
)
from services.workspace_service import OPENING_BALANCE_OFFSET_ACCOUNT_UNSET, WorkspaceManager


ROOT_DIR = Path(__file__).resolve().parents[2]
stages = StageStore(ROOT_DIR)
import_index = ImportIndex(ROOT_DIR / ".workflow" / "state.db")
workspace_manager = WorkspaceManager(ROOT_DIR)


def _sanitize_filename_stem(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return safe or "statement"


def _custom_profile_ui(profile_cfg: dict | None) -> dict | None:
    if not profile_cfg:
        return None
    return {
        "displayName": profile_cfg.get("display_name"),
        "encoding": profile_cfg.get("encoding"),
        "delimiter": profile_cfg.get("delimiter"),
        "skipRows": profile_cfg.get("skip_rows", 0),
        "skipFooterRows": profile_cfg.get("skip_footer_rows", 0),
        "reverseOrder": profile_cfg.get("reverse_order", True),
        "dateColumn": profile_cfg.get("date_column"),
        "dateFormat": profile_cfg.get("date_format"),
        "descriptionColumn": profile_cfg.get("description_column"),
        "secondaryDescriptionColumn": profile_cfg.get("secondary_description_column"),
        "amountMode": profile_cfg.get("amount_mode"),
        "amountColumn": profile_cfg.get("amount_column"),
        "debitColumn": profile_cfg.get("debit_column"),
        "creditColumn": profile_cfg.get("credit_column"),
        "balanceColumn": profile_cfg.get("balance_column"),
        "codeColumn": profile_cfg.get("code_column"),
        "noteColumn": profile_cfg.get("note_column"),
        "currency": profile_cfg.get("currency"),
    }


def _import_account_ui(config, account_id: str, account_cfg: dict) -> dict:
    source = import_source_summary(config, account_cfg)
    return {
        "id": account_id,
        "displayName": account_cfg.get("display_name", account_id),
        "institutionId": source.get("institution_id"),
        "institutionDisplayName": source.get("display_name") or "Custom CSV",
        "ledgerAccount": account_cfg.get("ledger_account", ""),
        "last4": account_cfg.get("last4"),
        "importMode": source["mode"],
        "importProfileId": source.get("profile_id"),
        "importProfile": _custom_profile_ui(source.get("profile")) if source["mode"] == "custom" else None,
    }


def _account_kind(account: str) -> str:
    prefix = account.split(":", 1)[0].strip().lower()
    if prefix == "assets":
        return "asset"
    if prefix in {"liabilities", "liability"}:
        return "liability"
    if prefix in {"expenses", "expense"}:
        return "expense"
    if prefix in {"income", "revenue"}:
        return "income"
    if prefix in {"equity", "capital"}:
        return "equity"
    return "other"


def _tracked_account_ui(
    config,
    account_id: str,
    account_cfg: dict,
    opening_by_id: dict,
    opening_by_ledger: dict,
) -> dict:
    import_account_id = str(account_cfg.get("import_account_id") or "").strip() or None
    linked_import_cfg = config.import_accounts.get(import_account_id or "", {}) if import_account_id else {}
    source = import_source_summary(config, linked_import_cfg) if linked_import_cfg else None
    institution_id = (
        canonical_template_id(account_cfg.get("institution"))
        or (source.get("institution_id") if source else None)
        or account_cfg.get("institution")
    )
    institution_display_name = (
        display_name_for(institution_id, fallback=str(institution_id))
        if institution_id
        else (source.get("display_name") if source else None)
    )
    opening_entry = opening_by_id.get(account_id)
    ledger_account = str(account_cfg.get("ledger_account", "")).strip()
    if opening_entry is None and ledger_account:
        opening_entry = opening_by_ledger.get(ledger_account)
    opening_balance_offset_account_id = None
    if opening_entry is not None:
        opening_balance_offset_account_id = _tracked_account_id_for_ledger_account(
            config,
            opening_entry.offset_account,
            exclude_account_id=account_id,
        )

    return {
        "id": account_id,
        "displayName": account_cfg.get("display_name", account_id),
        "ledgerAccount": ledger_account,
        "kind": _account_kind(ledger_account),
        "subtype": account_cfg.get("subtype"),
        "institutionId": institution_id,
        "institutionDisplayName": institution_display_name,
        "last4": account_cfg.get("last4"),
        "importAccountId": import_account_id,
        "importConfigured": bool(import_account_id),
        "importMode": source["mode"] if source else None,
        "importProfileId": source.get("profile_id") if source else None,
        "importProfile": _custom_profile_ui(source.get("profile")) if source and source["mode"] == "custom" else None,
        "openingBalance": str(opening_entry.amount) if opening_entry is not None else None,
        "openingBalanceDate": opening_entry.date if opening_entry is not None else None,
        "openingBalanceOffsetAccountId": opening_balance_offset_account_id,
    }


def _tracked_account_id_for_ledger_account(
    config,
    ledger_account: str | None,
    *,
    exclude_account_id: str | None = None,
) -> str | None:
    target = str(ledger_account or "").strip()
    if not target or target == OPENING_BALANCES_EQUITY:
        return None
    for tracked_account_id, tracked_account in config.tracked_accounts.items():
        if tracked_account_id == exclude_account_id:
            continue
        if str(tracked_account.get("ledger_account", "")).strip() == target:
            return tracked_account_id
    return None


def _opening_balance_offset_request_value(req) -> object:
    if "openingBalanceOffsetAccountId" not in req.model_fields_set:
        return OPENING_BALANCE_OFFSET_ACCOUNT_UNSET
    return req.openingBalanceOffsetAccountId


_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stages.cleanup_old(days=7)
    import_index.ensure_schema()
    try:
        config = workspace_manager.load_active_config()
        if config is not None:
            check_startup_drift(config.root_dir)
    except Exception:
        _log.warning("Startup drift check failed — skipping", exc_info=True)
    yield


app = FastAPI(title="Ledger Flow API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_workspace_config():
    config = workspace_manager.load_active_config()
    if config is None:
        raise HTTPException(status_code=409, detail="workspace_not_initialized")
    return config


def _rule_or_404(path: Path, rule_id: str) -> dict:
    rule = next((item for item in load_rules(path) if item["id"] == rule_id), None)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


def _same_resolved_path(left: str | None, right: Path) -> bool:
    if not left:
        return False
    try:
        return Path(left).resolve() == right.resolve()
    except OSError:
        return False


def _import_stage_payload(csv_path: str, year: str, import_account_id: str, data: dict) -> dict:
    payload = {
        "kind": "import",
        "status": "ready",
        "csvPath": csv_path,
        "year": year,
        "importAccountId": import_account_id,
        **data,
    }
    stage_id = stages.create(payload)
    payload["stageId"] = stage_id
    return payload


def _raise_import_preview_blocked(error: ImportPreviewBlockedError) -> None:
    raise HTTPException(status_code=400, detail=error.as_detail()) from error


def _unknown_stage_summary(groups: list[dict], selections: dict[str, dict]) -> dict:
    return {
        "groupCount": len(selections),
        "txnUpdates": sum(len(group["txns"]) for group in groups if group["groupKey"] in selections),
    }


def _filtered_unknown_selections(groups: list[dict], selections: dict[str, dict] | None) -> dict[str, dict]:
    group_keys = {group["groupKey"] for group in groups}
    return {
        group_key: selection
        for group_key, selection in (selections or {}).items()
        if group_key in group_keys
    }


def _find_resumable_unknown_stage(journal_path: Path) -> dict | None:
    return stages.find_latest(
        lambda payload: (
            payload.get("kind") == "unknowns"
            and payload.get("status") != "applied"
            and _same_resolved_path(payload.get("journalPath"), journal_path)
        )
    )


def _build_unknown_stage_payload(journal_path: Path, groups: list[dict], selections: dict[str, dict] | None = None) -> dict:
    normalized_selections = _filtered_unknown_selections(groups, selections)
    return {
        "kind": "unknowns",
        "status": "ready",
        "journalPath": str(journal_path.resolve()),
        "groups": groups,
        "selections": normalized_selections,
        "summary": _unknown_stage_summary(groups, normalized_selections),
    }


@app.get("/api/health")
def health() -> dict:
    try:
        ledger_version = run_cmd(["ledger", "--version"], ROOT_DIR).splitlines()[0]
        hledger_version = run_cmd(["hledger", "--version"], ROOT_DIR).splitlines()[0]
    except CommandError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "ok", "ledgerVersion": ledger_version, "hledgerVersion": hledger_version}


@app.get("/api/app/state")
def app_state() -> dict:
    config = workspace_manager.load_active_config()
    if config is None:
        return {
            "initialized": False,
            "workspacePath": None,
            "workspaceName": None,
            "institutions": [],
            "importAccounts": [],
            "trackedAccounts": [],
            "journals": 0,
            "csvInbox": 0,
            "institutionTemplates": list_templates(),
            "setup": workspace_manager.get_setup_state(None),
        }

    journals = list(config.journal_dir.glob("*.journal"))
    csvs = list(config.csv_dir.glob("*.csv"))
    import_accounts = [
        _import_account_ui(config, account_id, account_cfg)
        for account_id, account_cfg in sorted(config.import_accounts.items(), key=lambda x: x[0])
    ]
    institutions: dict[str, dict] = {}
    for account in import_accounts:
        institution_id = account["institutionId"]
        if institution_id and institution_id not in institutions:
            institutions[institution_id] = {
                "id": institution_id,
                "displayName": account["institutionDisplayName"],
            }
    opening_by_id, opening_by_ledger = opening_balance_index(config)
    tracked_accounts = [
        _tracked_account_ui(config, account_id, account_cfg, opening_by_id, opening_by_ledger)
        for account_id, account_cfg in sorted(config.tracked_accounts.items(), key=lambda x: x[0])
    ]
    return {
        "initialized": True,
        "workspacePath": str(config.root_dir.resolve()),
        "workspaceName": config.name,
        "institutions": list(institutions.values()),
        "importAccounts": import_accounts,
        "trackedAccounts": tracked_accounts,
        "journals": len(journals),
        "csvInbox": len(csvs),
        "institutionTemplates": list_templates(),
        "setup": workspace_manager.get_setup_state(config),
    }


@app.get("/api/dashboard/overview")
def dashboard_overview() -> dict:
    config = _require_workspace_config()
    try:
        return build_dashboard_overview(config)
    except CommodityMismatchError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/transactions/activity")
def transactions_activity(
    category: str | None = None,
    month: str | None = None,
    period: str | None = None,
) -> dict:
    config = _require_workspace_config()
    return build_activity_view(config, category=category, month=month, period=period)


@app.get("/api/transactions/register")
def transactions_register(accountId: str) -> dict:
    config = _require_workspace_config()
    try:
        return build_account_register(config, accountId)
    except CommodityMismatchError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/transactions/create")
def transactions_create(req: ManualTransactionRequest) -> dict:
    config = _require_workspace_config()
    tracked_account_cfg = config.tracked_accounts.get(req.trackedAccountId)
    if not tracked_account_cfg:
        raise HTTPException(status_code=404, detail=f"Tracked account not found: {req.trackedAccountId}")

    year = req.date[:4]
    journal_path = config.journal_dir / f"{year}.journal"
    accounts_dat = config.init_dir / "10-accounts.dat"
    currency = str(config.workspace.get("base_currency", "USD"))

    hash_before = check_drift(config.root_dir, journal_path)

    try:
        result = create_manual_transaction(
            journal_path=journal_path,
            accounts_dat=accounts_dat,
            tracked_account_cfg=tracked_account_cfg,
            txn_date=req.date,
            payee=req.payee,
            amount_str=req.amount,
            destination_account=req.destinationAccount,
            currency=currency,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        hash_after = hash_file(journal_path)
        source_account = tracked_account_cfg.get("name", req.trackedAccountId)
        emit_event(
            config.root_dir,
            event_type="manual_entry.created.v1",
            summary=f"Created manual entry: {req.payee or '(no payee)'} {req.amount} {currency}",
            payload={
                "date": req.date,
                "payee": req.payee or "",
                "amount": req.amount,
                "currency": currency,
                "destination_account": req.destinationAccount,
                "source_account": source_account,
            },
            journal_refs=[{
                "path": rel_path(journal_path, config.root_dir),
                "hash_before": hash_before,
                "hash_after": hash_after,
            }],
        )
    except Exception:
        _log.error("Event emission failed for transactions_create", exc_info=True)

    return result


@app.post("/api/transactions/manual-transfer-resolution/preview")
def transactions_manual_transfer_resolution_preview(req: ManualTransferResolutionRequest) -> dict:
    config = _require_workspace_config()
    try:
        return preview_manual_transfer_resolution(config, req.resolutionToken)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/transactions/manual-transfer-resolution/apply")
def transactions_manual_transfer_resolution_apply(req: ManualTransferResolutionRequest) -> dict:
    config = _require_workspace_config()

    # Pre-hash all journals — we can't know which one will be written until
    # the service resolves the token internally.
    journal_hashes: dict[str, str] = {}
    if config.journal_dir.is_dir():
        for jf in config.journal_dir.glob("*.journal"):
            journal_hashes[str(jf.resolve())] = check_drift(config.root_dir, jf)

    try:
        result = apply_manual_transfer_resolution(config, req.resolutionToken)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        journal_path = Path(result["journalPath"])
        hash_before = journal_hashes.get(str(journal_path.resolve()), hash_file(Path(result["backupPath"])))
        hash_after = hash_file(journal_path)
        emit_event(
            config.root_dir,
            event_type="transfer_resolution.applied.v1",
            summary=f"Transfer resolution: {result.get('payee', '')} {result.get('amount', '')}",
            payload={
                "journal_path": rel_path(journal_path, config.root_dir),
                "date": result.get("date", ""),
                "payee": result.get("payee", ""),
                "source_account": result.get("sourceAccountName", ""),
                "destination_account": result.get("destinationAccountName", ""),
                "amount": str(result.get("amount", "")),
            },
            journal_refs=[{
                "path": rel_path(journal_path, config.root_dir),
                "hash_before": hash_before,
                "hash_after": hash_after,
            }],
        )
    except Exception:
        _log.error("Event emission failed for transfer_resolution_apply", exc_info=True)

    return result


_STATUS_CYCLE = {
    TransactionStatus.unmarked: TransactionStatus.pending,
    TransactionStatus.pending: TransactionStatus.cleared,
    TransactionStatus.cleared: TransactionStatus.unmarked,
}


@app.post("/api/transactions/toggle-status")
def transactions_toggle_status(req: ToggleStatusRequest) -> dict:
    config = _require_workspace_config()
    journal_path = Path(req.journalPath)
    if not journal_path.is_file():
        raise HTTPException(status_code=404, detail="Journal file not found")

    parsed = parse_header(req.headerLine)
    if parsed is None:
        raise HTTPException(status_code=400, detail="Invalid header line")

    next_status = _STATUS_CYCLE[parsed.status]
    new_line = set_header_status(req.headerLine, next_status)

    if not _HEADER_RE.match(new_line):
        raise HTTPException(status_code=500, detail="Rewritten header is invalid")

    hash_before = check_drift(config.root_dir, journal_path)

    text = journal_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    match_indexes = [i for i, line in enumerate(lines) if line == req.headerLine]
    if len(match_indexes) == 0:
        raise HTTPException(status_code=404, detail="Header line not found in journal (stale data — try refreshing)")
    if len(match_indexes) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous: multiple matching header lines found")

    lines[match_indexes[0]] = new_line
    journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

    try:
        hash_after = hash_file(journal_path)
        emit_event(
            config.root_dir,
            event_type="transaction.status_toggled.v1",
            summary=f"Toggled status to {next_status.value}: {req.headerLine[:60]}",
            payload={
                "journal_path": rel_path(journal_path, config.root_dir),
                "header_line": req.headerLine,
                "previous_status": parsed.status.value,
                "new_status": next_status.value,
            },
            journal_refs=[{
                "path": rel_path(journal_path, config.root_dir),
                "hash_before": hash_before,
                "hash_after": hash_after,
            }],
        )
    except Exception:
        _log.error("Event emission failed for toggle_status", exc_info=True)

    return {"newStatus": next_status.value, "newHeaderLine": new_line}


@app.post("/api/workspace/bootstrap")
def workspace_bootstrap(req: WorkspaceBootstrapRequest) -> dict:
    try:
        root = workspace_manager.bootstrap_workspace(
            workspace_path=Path(req.workspacePath),
            workspace_name=req.workspaceName,
            base_currency=req.baseCurrency,
            start_year=req.startYear,
            import_accounts=[account.model_dump() for account in req.importAccounts],
        )
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"ok": True, "workspacePath": str(root)}


@app.post("/api/workspace/select")
def workspace_select(req: WorkspaceSelectRequest) -> dict:
    root = Path(req.workspacePath).resolve()
    cfg = root / "settings" / "workspace.toml"
    if not cfg.exists():
        raise HTTPException(status_code=404, detail="workspace config not found")

    workspace_manager.set_active_workspace(root)
    return {"ok": True, "workspacePath": str(root)}


@app.post("/api/workspace/import-accounts")
def workspace_import_account_upsert(req: WorkspaceImportAccountUpsertRequest) -> dict:
    config = _require_workspace_config()
    try:
        account_id, account_cfg = workspace_manager.upsert_import_account(
            config,
            {
                "institutionId": req.institutionId,
                "displayName": req.displayName,
                "ledgerAccount": req.ledgerAccount,
                "subtype": req.subtype,
                "last4": req.last4,
            },
            account_id=req.accountId,
            opening_balance=req.openingBalance,
            opening_balance_date=req.openingBalanceDate,
            opening_balance_offset_account_id=_opening_balance_offset_request_value(req),
        )
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    refreshed = _require_workspace_config()
    opening_by_id, opening_by_ledger = opening_balance_index(refreshed)
    tracked_account_id = str(account_cfg.get("tracked_account_id") or account_id)
    return {
        "ok": True,
        "importAccount": _import_account_ui(refreshed, account_id, account_cfg),
        "trackedAccount": _tracked_account_ui(
            refreshed,
            tracked_account_id,
            refreshed.tracked_accounts.get(tracked_account_id, {}),
            opening_by_id,
            opening_by_ledger,
        ),
    }


@app.post("/api/workspace/custom-import-accounts")
def workspace_custom_import_account_upsert(req: CustomImportAccountUpsertRequest) -> dict:
    config = _require_workspace_config()
    try:
        account_id, account_cfg = workspace_manager.upsert_custom_import_account(
            config,
            {
                "displayName": req.displayName,
                "ledgerAccount": req.ledgerAccount,
                "subtype": req.subtype,
                "last4": req.last4,
                "customProfile": req.customProfile.model_dump(),
            },
            account_id=req.accountId,
            opening_balance=req.openingBalance,
            opening_balance_date=req.openingBalanceDate,
            opening_balance_offset_account_id=_opening_balance_offset_request_value(req),
        )
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    refreshed = _require_workspace_config()
    opening_by_id, opening_by_ledger = opening_balance_index(refreshed)
    tracked_account_id = str(account_cfg.get("tracked_account_id") or account_id)
    return {
        "ok": True,
        "importAccount": _import_account_ui(refreshed, account_id, account_cfg),
        "trackedAccount": _tracked_account_ui(
            refreshed,
            tracked_account_id,
            refreshed.tracked_accounts.get(tracked_account_id, {}),
            opening_by_id,
            opening_by_ledger,
        ),
    }


@app.get("/api/tracked-accounts")
def tracked_accounts_list() -> dict:
    config = _require_workspace_config()
    opening_by_id, opening_by_ledger = opening_balance_index(config)
    rows = [
        _tracked_account_ui(config, account_id, account_cfg, opening_by_id, opening_by_ledger)
        for account_id, account_cfg in sorted(
            config.tracked_accounts.items(),
            key=lambda item: str(item[1].get("display_name", item[0])),
        )
    ]
    return {"trackedAccounts": rows, "institutionTemplates": list_templates()}


@app.post("/api/tracked-accounts")
def tracked_account_upsert(req: TrackedAccountUpsertRequest) -> dict:
    config = _require_workspace_config()
    try:
        account_id, account_cfg = workspace_manager.upsert_tracked_account(
            config,
            {
                "displayName": req.displayName,
                "ledgerAccount": req.ledgerAccount,
                "subtype": req.subtype,
                "institutionId": req.institutionId,
                "last4": req.last4,
            },
            account_id=req.accountId,
            opening_balance=req.openingBalance,
            opening_balance_date=req.openingBalanceDate,
            opening_balance_offset_account_id=_opening_balance_offset_request_value(req),
        )
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    refreshed = _require_workspace_config()
    opening_by_id, opening_by_ledger = opening_balance_index(refreshed)
    return {
        "ok": True,
        "trackedAccount": _tracked_account_ui(
            refreshed,
            account_id,
            refreshed.tracked_accounts.get(account_id, account_cfg),
            opening_by_id,
            opening_by_ledger,
        ),
    }


@app.get("/api/import/candidates")
def import_candidates() -> dict:
    config = _require_workspace_config()
    rows = []
    for c in scan_candidates(config):
        row = c.__dict__.copy()
        account_id = row.get("detected_import_account_id")
        account_cfg = config.import_accounts.get(account_id or "")
        row["detected_import_account_display_name"] = (
            account_cfg.get("display_name") if account_cfg else None
        )
        row["detected_institution_display_name"] = (
            import_source_summary(config, account_cfg).get("display_name") if account_cfg else None
        )
        rows.append(row)

    import_accounts = [
        _import_account_ui(config, account_id, account_cfg)
        for account_id, account_cfg in sorted(config.import_accounts.items(), key=lambda x: x[0])
    ]
    return {"candidates": rows, "importAccounts": import_accounts}


@app.post("/api/import/custom-profile/inspect")
async def import_custom_profile_inspect(
    file: UploadFile = File(...),
    encoding: str | None = Form(default=None),
    delimiter: str | None = Form(default=None),
    skipRows: int = Form(default=0),
    skipFooterRows: int = Form(default=0),
) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        return inspect_csv_bytes(
            content,
            encoding=encoding or None,
            delimiter=delimiter or None,
            skip_rows=skipRows,
            skip_footer_rows=skipFooterRows,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/import/upload")
async def import_upload(
    file: UploadFile = File(...),
    year: str = Form(...),
    importAccountId: str = Form(...),
    preview: bool = Form(default=False),
) -> dict:
    config = _require_workspace_config()

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    if importAccountId not in config.import_accounts:
        raise HTTPException(status_code=400, detail="Unknown import account selected")

    original_stem = _sanitize_filename_stem(Path(file.filename).stem)
    safe_name = f"{year}__{importAccountId}__{original_stem}-{uuid4().hex[:8]}.csv"
    dest = config.csv_dir / safe_name
    dest.parent.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    dest.write_bytes(content)

    if preview:
        try:
            data = preview_import_safely(
                config,
                dest,
                year,
                importAccountId,
                keep_file_on_failure=False,
            )
        except ImportPreviewBlockedError as e:
            _raise_import_preview_blocked(e)
        return {
            "uploaded": True,
            "fileName": safe_name,
            "absPath": str(dest.resolve()),
            "sizeBytes": len(content),
            **_import_stage_payload(str(dest.resolve()), year, importAccountId, data),
        }

    return {
        "uploaded": True,
        "fileName": safe_name,
        "absPath": str(dest.resolve()),
        "sizeBytes": len(content),
    }


@app.get("/api/journals")
def journals() -> dict:
    config = _require_workspace_config()
    rows = []
    for path in sorted(config.journal_dir.glob("*.journal")):
        rows.append(
            {
                "fileName": path.name,
                "absPath": str(path.resolve()),
                "sizeBytes": path.stat().st_size,
                "mtime": path.stat().st_mtime,
            }
        )
    return {"journals": rows}


@app.get("/api/accounts")
def accounts() -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    category_accounts = list_category_accounts(accounts_dat)
    return {
        "accounts": category_accounts,
        "categoryAccounts": category_accounts,
        "allAccounts": list_known_accounts(accounts_dat),
    }


@app.get("/api/rules")
def rules_list() -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    path = ensure_rules_store(config.init_dir, accounts_dat)
    return {"rules": load_rules(path)}


@app.post("/api/rules")
def rules_create(req: RuleCreateRequest) -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    known_accounts = set(list_known_accounts(accounts_dat))
    requested_actions = [a.model_dump() for a in req.actions]
    requested_account = extract_set_account({"actions": requested_actions})
    if requested_account is not None and requested_account not in known_accounts:
        raise HTTPException(status_code=400, detail=f"Unknown account: {requested_account}")
    path = ensure_rules_store(config.init_dir, accounts_dat)
    try:
        rule = create_rule(
            path,
            name=req.name,
            conditions=[c.model_dump() for c in req.conditions],
            actions=requested_actions,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"rule": rule}


@app.post("/api/accounts")
def accounts_create(req: CreateAccountRequest) -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    try:
        added, warning = create_account(accounts_dat, req.account, req.accountType, req.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"added": added, "warning": warning}


@app.post("/api/import/preview")
def import_preview(req: ImportPreviewRequest) -> dict:
    config = _require_workspace_config()
    if req.importAccountId not in config.import_accounts:
        raise HTTPException(status_code=400, detail="Unknown import account selected")
    try:
        data = preview_import_safely(
            config,
            Path(req.csvPath),
            req.year,
            req.importAccountId,
            keep_file_on_failure=True,
        )
    except ImportPreviewBlockedError as e:
        _raise_import_preview_blocked(e)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return _import_stage_payload(req.csvPath, req.year, req.importAccountId, data)


@app.post("/api/import/remove")
def import_remove(req: ImportCandidateRemoveRequest) -> dict:
    config = _require_workspace_config()
    try:
        removed_path = remove_inbox_csv(config, Path(req.csvPath))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Statement not found") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "removed": True,
        "csvPath": removed_path,
        "fileName": Path(removed_path).name,
    }


@app.post("/api/import/apply")
def import_apply(req: StageApplyRequest) -> dict:
    config = _require_workspace_config()
    try:
        stage = stages.load(req.stageId)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e

    if stage.get("kind") != "import":
        raise HTTPException(status_code=400, detail="stage kind mismatch")
    if stage.get("status") == "applied":
        return stage

    journal = Path(stage["targetJournalPath"])
    hash_before = check_drift(config.root_dir, journal)
    backup = backup_file(journal, "import") if journal.exists() else None

    try:
        journal_path, appended_count, skipped_duplicate_count, conflicts = apply_import(config, stage)
    except CommandError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    archived_csv_path = None
    source_csv_warning = None
    try:
        archived_csv_path = archive_inbox_csv(
            config,
            Path(stage["csvPath"]),
            stage["year"],
            stage["importAccountId"],
            stage.get("sourceFileSha256", ""),
        )
    except OSError as e:
        source_csv_warning = f"Imported successfully, but source CSV could not be archived: {e}"

    stage["status"] = "applied"
    stage["result"] = {
        "applied": True,
        "backupPath": str(backup.resolve()) if backup else None,
        "journalPath": journal_path,
        "appendedTxnCount": appended_count,
        "skippedDuplicateCount": skipped_duplicate_count,
        "conflicts": conflicts,
        "archivedCsvPath": archived_csv_path,
        "sourceCsvWarning": source_csv_warning,
    }
    history_entry = record_applied_import(config, stage)
    stage["result"]["historyId"] = history_entry["id"]
    stages.save(req.stageId, stage)

    try:
        hash_after = hash_file(journal)
        source_file = Path(stage.get("csvPath", "")).name
        emit_event(
            config.root_dir,
            event_type="import.applied.v1",
            summary=f"Imported {appended_count} transactions from {source_file}",
            payload={
                "journal_path": rel_path(journal, config.root_dir),
                "source_file": source_file,
                "account_id": stage.get("importAccountId", ""),
                "transactions_added": appended_count,
                "duplicates_skipped": skipped_duplicate_count,
                "conflicts": conflicts,
                "history_id": history_entry["id"],
            },
            journal_refs=[{
                "path": rel_path(journal, config.root_dir),
                "hash_before": hash_before,
                "hash_after": hash_after,
            }],
        )
    except Exception:
        _log.error("Event emission failed for import_apply", exc_info=True)

    return stage


@app.get("/api/import/history")
def import_history() -> dict:
    config = _require_workspace_config()
    return {"history": list_import_history(config)}


@app.post("/api/import/undo")
def import_undo(req: ImportUndoRequest) -> dict:
    config = _require_workspace_config()

    # Resolve journal path before mutation for drift check.
    journal_path = None
    hash_before = None
    try:
        for entry_item in list_import_history(config):
            if str(entry_item.get("id")) == req.historyId:
                jp = entry_item.get("targetJournalPath")
                if jp:
                    journal_path = Path(str(jp))
                    hash_before = check_drift(config.root_dir, journal_path)
                break
    except Exception:
        _log.warning("Could not resolve journal path for import undo drift check", exc_info=True)

    try:
        entry = undo_import(config, req.historyId)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="import history entry not found") from e
    except (FileNotFoundError, OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        if journal_path is not None:
            hash_after = hash_file(journal_path)
            removed_count = entry.get("undo", {}).get("removedTxnCount", 0)
            emit_event(
                config.root_dir,
                event_type="import.undone.v1",
                summary=f"Undid import {req.historyId}: removed {removed_count} transactions",
                payload={
                    "journal_path": rel_path(journal_path, config.root_dir),
                    "history_id": req.historyId,
                    "transactions_removed": removed_count,
                },
                journal_refs=[{
                    "path": rel_path(journal_path, config.root_dir),
                    "hash_before": hash_before,
                    "hash_after": hash_after,
                }],
            )
    except Exception:
        _log.error("Event emission failed for import_undo", exc_info=True)

    return {"entry": entry}


@app.post("/api/unknowns/scan")
def unknown_scan(req: UnknownScanRequest) -> dict:
    config = _require_workspace_config()
    journal_path = Path(req.journalPath)
    if not journal_path.exists():
        raise HTTPException(status_code=404, detail="journal not found")

    accounts_dat = config.init_dir / "10-accounts.dat"
    rule_path = ensure_rules_store(config.init_dir, accounts_dat)
    data = scan_unknowns(journal_path, load_rules(rule_path), config.import_accounts, config.tracked_accounts)
    existing_stage = _find_resumable_unknown_stage(journal_path)
    if existing_stage is not None:
        payload = {
            **existing_stage,
            **_build_unknown_stage_payload(journal_path, data["groups"], existing_stage.get("selections")),
            "stageId": existing_stage["stageId"],
        }
        stages.save(existing_stage["stageId"], payload)
        return payload

    payload = _build_unknown_stage_payload(journal_path, data["groups"])
    stage_id = stages.create(payload)
    payload["stageId"] = stage_id
    return payload


@app.post("/api/unknowns/stage-mappings")
def unknown_stage_mappings(req: UnknownStageRequest) -> dict:
    try:
        stage = stages.load(req.stageId)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e

    if stage.get("kind") != "unknowns":
        raise HTTPException(status_code=400, detail="stage kind mismatch")

    selections = {
        selection.groupKey: selection.model_dump(exclude_none=True)
        for selection in req.selections
    }
    stage["selections"] = selections
    stage["summary"] = _unknown_stage_summary(stage["groups"], selections)
    stages.save(req.stageId, stage)
    return stage


@app.post("/api/unknowns/apply")
def unknown_apply(req: StageApplyRequest) -> dict:
    config = _require_workspace_config()
    try:
        stage = stages.load(req.stageId)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e

    if stage.get("kind") != "unknowns":
        raise HTTPException(status_code=400, detail="stage kind mismatch")
    if stage.get("status") == "applied":
        return stage

    selections = stage.get("selections") or {}
    if not selections:
        raise HTTPException(status_code=400, detail="no mappings staged")

    journal_path = Path(stage["journalPath"])
    accounts_dat = config.init_dir / "10-accounts.dat"
    archived_manual = journal_path.parent / "archived-manual.journal"

    # Pre-mutation hashes for all files that may be written.
    journal_hash_before = check_drift(config.root_dir, journal_path)
    accounts_hash_before = hash_file(accounts_dat)
    archive_hash_before = hash_file(archived_manual)

    journal_backup = backup_file(journal_path, "unknowns")
    accounts_backup = backup_file(accounts_dat, "rules")

    try:
        txn_updates, warnings = apply_unknown_mappings(
            journal_path=journal_path,
            accounts_dat=accounts_dat,
            selections=selections,
            scanned_groups=stage["groups"],
            tracked_accounts=config.tracked_accounts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    stage["status"] = "applied"
    stage["result"] = {
        "applied": True,
        "backupPaths": [str(journal_backup.resolve()), str(accounts_backup.resolve())],
        "updatedTxnCount": txn_updates,
        "warnings": warnings,
    }
    stages.save(req.stageId, stage)

    try:
        journal_hash_after = hash_file(journal_path)
        accounts_hash_after = hash_file(accounts_dat)
        archive_hash_after = hash_file(archived_manual)

        # Count match selections for payload.
        match_ids = [
            sel.get("matchId") or ""
            for sel in selections.values()
            if sel.get("selectionType") == "match"
        ]

        refs = [
            {"path": rel_path(journal_path, config.root_dir), "hash_before": journal_hash_before, "hash_after": journal_hash_after},
            {"path": rel_path(accounts_dat, config.root_dir), "hash_before": accounts_hash_before, "hash_after": accounts_hash_after},
        ]
        if archive_hash_after != archive_hash_before:
            refs.append({"path": rel_path(archived_manual, config.root_dir), "hash_before": archive_hash_before, "hash_after": archive_hash_after})

        mappings_applied = sum(1 for sel in selections.values() if sel.get("selectionType") == "category")
        emit_event(
            config.root_dir,
            event_type="unknowns.applied.v1",
            summary=f"Applied {mappings_applied} mappings and {len(match_ids)} matches",
            payload={
                "journal_path": rel_path(journal_path, config.root_dir),
                "mappings_applied": mappings_applied,
                "matches_applied": len(match_ids),
                "match_ids": match_ids,
                "warnings": warnings,
            },
            journal_refs=refs,
        )
    except Exception:
        _log.error("Event emission failed for unknown_apply", exc_info=True)

    return stage


@app.post("/api/rules/payee")
def create_payee_rule(req: PayeeRuleRequest) -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    known_accounts = set(list_known_accounts(accounts_dat))
    if req.account not in known_accounts:
        raise HTTPException(status_code=400, detail=f"Unknown account: {req.account}")
    path = ensure_rules_store(config.init_dir, accounts_dat)
    try:
        rule, changed = upsert_payee_rule(path, req.payee, req.account)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"added": changed, "warning": None, "rule": rule}


@app.post("/api/rules/reorder")
def rules_reorder(req: RuleReorderRequest) -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    path = ensure_rules_store(config.init_dir, accounts_dat)
    try:
        rules = reorder_rules(path, req.orderedIds)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"rules": rules}


@app.post("/api/rules/{rule_id}")
def rules_update(rule_id: str, req: RuleUpdateRequest) -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    known_accounts = set(list_known_accounts(accounts_dat))
    requested_actions = [a.model_dump() for a in req.actions] if req.actions is not None else None
    requested_account = extract_set_account({"actions": requested_actions}) if requested_actions is not None else None
    if requested_account is not None and requested_account not in known_accounts:
        raise HTTPException(status_code=400, detail=f"Unknown account: {requested_account}")
    path = ensure_rules_store(config.init_dir, accounts_dat)
    try:
        rule = update_rule(
            path,
            rule_id,
            name=req.name,
            conditions=[c.model_dump() for c in req.conditions] if req.conditions is not None else None,
            actions=requested_actions,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"rule": rule}


@app.post("/api/rules/{rule_id}/history/scan")
def rules_history_scan(rule_id: str, req: RuleHistoryScanRequest) -> dict:
    config = _require_workspace_config()
    journal_path = Path(req.journalPath)
    if not journal_path.exists():
        raise HTTPException(status_code=404, detail="journal not found")

    accounts_dat = config.init_dir / "10-accounts.dat"
    path = ensure_rules_store(config.init_dir, accounts_dat)
    rule = _rule_or_404(path, rule_id)
    try:
        data = scan_rule_reapply(journal_path, rule, config.import_accounts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    payload = {
        "kind": "rule_history",
        "status": "ready",
        "ruleId": rule_id,
        "ruleName": rule.get("name"),
        "journalPath": str(journal_path.resolve()),
        "targetAccount": data["targetAccount"],
        "candidates": data["candidates"],
        "warnings": data["warnings"],
        "summary": data["summary"],
    }
    stage_id = stages.create(payload)
    payload["stageId"] = stage_id
    return payload


@app.post("/api/rules/history/apply")
def rules_history_apply(req: RuleHistoryApplyRequest) -> dict:
    config = _require_workspace_config()
    try:
        stage = stages.load(req.stageId)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e

    if stage.get("kind") != "rule_history":
        raise HTTPException(status_code=400, detail="stage kind mismatch")
    if stage.get("status") == "applied":
        return stage

    selected_candidate_ids = [candidate_id for candidate_id in req.selectedCandidateIds if candidate_id]
    if not selected_candidate_ids:
        raise HTTPException(status_code=400, detail="no historical matches selected")

    journal_path = Path(stage["journalPath"])
    accounts_dat = config.init_dir / "10-accounts.dat"
    hash_before = check_drift(config.root_dir, journal_path)
    journal_backup = backup_file(journal_path, "rule-history")

    try:
        updated_count, warnings = apply_rule_reapply(
            journal_path=journal_path,
            accounts_dat=accounts_dat,
            candidates=stage.get("candidates") or [],
            selected_candidate_ids=selected_candidate_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    stage["status"] = "applied"
    stage["selectedCandidateIds"] = selected_candidate_ids
    stage["result"] = {
        "applied": True,
        "backupPath": str(journal_backup.resolve()),
        "updatedTxnCount": updated_count,
        "warnings": warnings,
    }
    stages.save(req.stageId, stage)

    try:
        hash_after = hash_file(journal_path)
        emit_event(
            config.root_dir,
            event_type="rule.history_applied.v1",
            summary=f"Applied rule history: {updated_count} transactions updated",
            payload={
                "journal_path": rel_path(journal_path, config.root_dir),
                "transactions_updated": updated_count,
                "selected_candidate_count": len(selected_candidate_ids),
                "warnings": warnings,
            },
            journal_refs=[{
                "path": rel_path(journal_path, config.root_dir),
                "hash_before": hash_before,
                "hash_after": hash_after,
            }],
        )
    except Exception:
        _log.error("Event emission failed for rules_history_apply", exc_info=True)

    return stage


@app.delete("/api/rules/{rule_id}")
def rules_delete(rule_id: str) -> dict:
    config = _require_workspace_config()
    accounts_dat = config.init_dir / "10-accounts.dat"
    path = ensure_rules_store(config.init_dir, accounts_dat)
    deleted = delete_rule(path, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"deleted": True}


@app.get("/api/stages/{stage_id}")
def get_stage(stage_id: str) -> dict:
    try:
        return stages.load(stage_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e


@app.delete("/api/stages/{stage_id}")
def delete_stage(stage_id: str) -> dict:
    stages.delete(stage_id)
    return {"deleted": True, "stageId": stage_id}
