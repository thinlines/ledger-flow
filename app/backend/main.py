from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from importlib import resources
import logging
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4, uuid7

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from models import (
    AccountCloseRequest,
    AccountNameRequest,
    AccountSubtypeRequest,
    ImportCandidateRemoveRequest,
    CustomImportAccountUpsertRequest,
    CreateAccountRequest,
    DeleteTransactionRequest,
    ImportPreviewRequest,
    ImportUndoRequest,
    ManualTransactionRequest,
    PayeeRuleRequest,
    ReassignAccountRequest,
    RecategorizeTransactionRequest,
    ReconcileRequest,
    ReconciliationDuplicateResolutionRequest,
    ReconciliationDuplicateReviewRequest,
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
    UnmatchTransactionRequest,
    UpdateNotesRequest,
    WorkspaceImportAccountUpsertRequest,
    WorkspaceBootstrapRequest,
    WorkspaceSelectRequest,
)
from services.category_suggestion_service import suggest_category
from services.event_log_service import check_startup_drift, rel_path
from services.git_snapshot_service import hours_since_last_snapshot, snapshot_commit
from services.header_parser import TransactionStatus, parse_header, set_header_status, HEADER_RE as _HEADER_RE
from services import journal_writer
from services.undo_service import UndoOutcome, is_undoable_type, undo_event
from services.event_log_service import read_events as _read_events_log
from services.journal_block_service import find_transaction_block
from services.journal_query_service import TXN_START_RE
from services.projection_service import (
    find_projected_transaction,
    find_projected_transaction_at,
    refresh_projection,
)
from services.transfer_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE, rewrite_posting_account
from services.account_register_service import build_account_register
from services.commodity_service import CommodityMismatchError
from services.custom_csv_service import inspect_csv_bytes
from services.activity_service import build_activity_view
from services.dashboard_service import build_dashboard_overview, query_dashboard_transactions
from services.direction_service import build_dashboard_direction
from services.unified_transactions_service import (
    UnifiedTransactionFilters,
    build_unified_transactions,
)
from services.import_history_service import list_import_history, record_applied_import, undo_import
from services.import_service import (
    ImportPreviewBlockedError,
    apply_import,
    archive_inbox_csv,
    preview_import_safely,
    remove_inbox_csv,
    scan_candidates,
)
from services.manual_entry_service import create_manual_transaction
from services.import_profile_service import import_source_summary
from services.institution_registry import canonical_template_id, display_name_for, list_templates
from services.ledger_runner import CommandError, run_cmd
from services.opening_balance_service import OPENING_BALANCES_EQUITY, opening_balance_index
from services.reconciliation_context_service import build_reconciliation_context
from services.reconciliation_duplicate_service import (
    build_duplicate_review_payload,
    resolve_duplicate_candidate,
)
from services.reconciliation_service import (
    AssertionFailure,
    latest_reconciliation_date,
    latest_reconciliation_dates_by_tracked_id,
    parse_closing_balance,
    reconciliation_status as compute_reconciliation_status,
    verify_assertion,
    write_assertion_transaction,
)
from services.rule_reapply_service import apply_rule_reapply, scan_rule_reapply
from services.stage_store import StageNotFoundError, StageStore
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
from services.account_declaration_service import (
    AccountNotDeclared,
    DeclarationInUse,
    close_account,
    create_account,
    delete_block_reason,
    delete_declaration,
    reopen_account,
    set_subtype,
)
from services.projection_service import refresh_projection
from services.reference_data_service import (
    account_subtypes,
    list_account_names,
    list_category_account_names,
    list_managed_accounts,
    posting_counts_by_account,
)
from services.unknowns_service import (
    apply_unknown_mappings,
    list_known_accounts,
    scan_unknowns,
)
from services.workspace_service import (
    ACCOUNT_SUBTYPE_KIND,
    OPENING_BALANCE_OFFSET_ACCOUNT_UNSET,
    WorkspaceManager,
)


ROOT_DIR = Path(os.environ.get("LEDGER_FLOW_ROOT", Path(__file__).resolve().parents[2])).expanduser().resolve()
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


def _transaction_counts_by_ledger_account(config) -> dict[str, int]:
    """Return {ledger_account: count} from the projected reference data."""
    try:
        return posting_counts_by_account(config)
    except OSError:
        return {}


def _projected_subtypes(config) -> dict[str, str]:
    """{account name: lf_subtype} from the projection — the canonical
    subtype source since issue #19 (config.toml no longer stores it)."""
    try:
        return account_subtypes(config)
    except OSError:
        return {}


def _tracked_account_ui(
    config,
    account_id: str,
    account_cfg: dict,
    opening_by_id: dict,
    opening_by_ledger: dict,
    reconciliation_status_by_id: dict[str, dict] | None = None,
    last_reconciled_by_id: dict[str, "date"] | None = None,
    subtype_by_ledger: dict[str, str] | None = None,
) -> dict:
    if subtype_by_ledger is None:
        subtype_by_ledger = _projected_subtypes(config)
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

    if reconciliation_status_by_id is None:
        reconciliation_status = {"ok": True}
    else:
        reconciliation_status = reconciliation_status_by_id.get(account_id, {"ok": True})

    last_reconciled_date = None
    if last_reconciled_by_id is not None:
        d = last_reconciled_by_id.get(account_id)
        if d is not None:
            last_reconciled_date = d.isoformat()

    return {
        "id": account_id,
        "displayName": account_cfg.get("display_name", account_id),
        "ledgerAccount": ledger_account,
        "kind": _account_kind(ledger_account),
        "subtype": subtype_by_ledger.get(ledger_account),
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
        "minimumPayment": str(opening_entry.minimum_payment) if opening_entry and opening_entry.minimum_payment is not None else None,
        "reconciliationStatus": reconciliation_status,
        "lastReconciledDate": last_reconciled_date,
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
    # Stages moved into the workspace database; drop the retired JSON store.
    shutil.rmtree(ROOT_DIR / ".workflow" / "stages", ignore_errors=True)
    config = None
    try:
        config = workspace_manager.load_active_config()
        if config is not None:
            StageStore(config).cleanup_old(days=7)
            check_startup_drift(config.root_dir)
    except Exception:
        _log.warning("Startup drift check failed — skipping", exc_info=True)
    try:
        if config is None:
            config = workspace_manager.load_active_config()
        if config is not None:
            age = hours_since_last_snapshot(config.root_dir)
            if age is None or age >= 24:
                snapshot_commit(config.root_dir, trigger="startup")
    except Exception:
        _log.warning("Startup git snapshot failed — skipping", exc_info=True)
    yield
    try:
        shutdown_config = workspace_manager.load_active_config()
        if shutdown_config is not None:
            snapshot_commit(shutdown_config.root_dir, trigger="shutdown")
    except Exception:
        _log.warning("Shutdown git snapshot failed — skipping", exc_info=True)


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


def _import_stage_payload(config, csv_path: str, year: str, import_account_id: str, data: dict) -> dict:
    payload = {
        "kind": "import",
        "status": "ready",
        "csvPath": csv_path,
        "year": year,
        "importAccountId": import_account_id,
        **data,
    }
    stage_id = StageStore(config).create(
        payload, base_files=[Path(payload["targetJournalPath"])]
    )
    payload["stageId"] = stage_id
    return payload


def _raise_import_preview_blocked(error: ImportPreviewBlockedError) -> None:
    raise HTTPException(status_code=400, detail=error.as_detail()) from error


def _unknown_stage_summary(groups: list[dict], selections: dict[str, dict]) -> dict:
    selected_group_keys = {
        sel.get("groupKey")
        for sel in selections.values()
        if sel.get("groupKey")
    }
    return {
        "groupCount": len(selected_group_keys),
        "txnUpdates": len(selections),
    }


def _group_key_for_txn(groups: list[dict], txn_id: str) -> str:
    for group in groups:
        for txn in group.get("txns", []):
            if txn.get("txnId") == txn_id:
                return group.get("groupKey", "")
    return ""


def _filtered_unknown_selections(groups: list[dict], selections: dict[str, dict] | None) -> dict[str, dict]:
    valid_txn_ids = {txn["txnId"] for group in groups for txn in group["txns"]}
    return {
        txn_id: selection
        for txn_id, selection in (selections or {}).items()
        if txn_id in valid_txn_ids
    }


def _find_resumable_unknown_stage(config, journal_path: Path) -> dict | None:
    return StageStore(config).find_latest(
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
    reconciliation_status_map = compute_reconciliation_status(config)
    last_reconciled_map = latest_reconciliation_dates_by_tracked_id(config)
    subtype_map = _projected_subtypes(config)
    tracked_accounts = [
        _tracked_account_ui(config, account_id, account_cfg, opening_by_id, opening_by_ledger, reconciliation_status_map, last_reconciled_map, subtype_map)
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


@app.get("/api/dashboard/direction")
def dashboard_direction() -> dict:
    config = _require_workspace_config()
    try:
        return build_dashboard_direction(config)
    except CommodityMismatchError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/dashboard/transactions")
def dashboard_transactions(
    period: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    if period is None:
        raise HTTPException(status_code=422, detail="Invalid period format. Expected YYYY-MM.")
    config = _require_workspace_config()
    try:
        return query_dashboard_transactions(
            config, period=period, category=category, limit=limit, offset=offset
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


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


@app.get("/api/transactions")
def transactions_unified(
    accounts: str | None = None,
    categories: str | None = None,
    period: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    month: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> dict:
    config = _require_workspace_config()
    filters = UnifiedTransactionFilters(
        accounts=[a.strip() for a in accounts.split(",") if a.strip()] if accounts else [],
        categories=[c.strip() for c in categories.split(",") if c.strip()] if categories else [],
        period=period,
        from_date=date.fromisoformat(from_date) if from_date else None,
        to_date=date.fromisoformat(to_date) if to_date else None,
        month=month,
        status=[s.strip() for s in status.split(",") if s.strip()] if status else None,
        search=search,
    )
    try:
        return build_unified_transactions(config, filters)
    except CommodityMismatchError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _resolve_source_tracked_account(config, req: ManualTransactionRequest) -> tuple[str, dict]:
    """Resolve the source tracked account from a create request.

    Accepts either the internal tracked account id (existing UI payload) or a
    user-facing source account selector: a fully-qualified Ledger account name.
    """
    if (req.trackedAccountId is None) == (req.sourceAccount is None):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of 'trackedAccountId' or 'sourceAccount'.",
        )
    if req.trackedAccountId is not None:
        tracked_account_cfg = config.tracked_accounts.get(req.trackedAccountId)
        if not tracked_account_cfg:
            raise HTTPException(status_code=404, detail=f"Tracked account not found: {req.trackedAccountId}")
        return req.trackedAccountId, tracked_account_cfg

    selector = str(req.sourceAccount or "").strip()
    matches = [
        (tracked_account_id, tracked_account)
        for tracked_account_id, tracked_account in config.tracked_accounts.items()
        if str(tracked_account.get("ledger_account", "")).strip() == selector
    ]
    if not matches:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No tracked account matches source account '{selector}'. "
                "Use a fully-qualified Ledger account name of a tracked account."
            ),
        )
    if len(matches) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Source account '{selector}' is ambiguous: it matches "
                f"{len(matches)} tracked accounts."
            ),
        )
    return matches[0]


@app.post("/api/transactions/create")
def transactions_create(req: ManualTransactionRequest) -> dict:
    config = _require_workspace_config()
    tracked_account_id, tracked_account_cfg = _resolve_source_tracked_account(config, req)

    year = req.date[:4]
    journal_path = config.journal_dir / f"{year}.journal"
    accounts_dat = config.init_dir / "10-accounts.dat"
    currency = str(config.workspace.get("base_currency", "USD"))
    source_account = tracked_account_cfg.get("name", tracked_account_id)

    result: dict
    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="manual-entry",
        event_type="manual_entry.created.v1",
    ) as mut:
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
        mut.summary = f"Created manual entry: {req.payee or '(no payee)'} {req.amount} {currency}"
        mut.payload = {
            "date": req.date,
            "payee": req.payee or "",
            "amount": req.amount,
            "currency": currency,
            "destination_account": req.destinationAccount,
            "source_account": source_account,
            "txn_id": result["txnId"],
        }

    return {**result, "eventId": mut.event_id}


_STATUS_CYCLE = {
    TransactionStatus.unmarked: TransactionStatus.pending,
    TransactionStatus.pending: TransactionStatus.cleared,
    TransactionStatus.cleared: TransactionStatus.unmarked,
}


_STALE_TRANSACTION_DETAIL = (
    "This transaction changed since it was loaded — refresh and try again."
)


def _locate_projected_transaction(config, txn_id: str, block_hash: str):
    """The stable-identity locate ritual shared by every row mutation:
    self-heal the projection, look the transaction up by id, reject only
    true block-level staleness (hash mismatch)."""
    refresh_projection(config)
    ref = find_projected_transaction(config, txn_id)
    if ref is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found (stale data — try refreshing)",
        )
    if block_hash != ref.raw_block_hash:
        raise HTTPException(status_code=409, detail=_STALE_TRANSACTION_DETAIL)
    return ref


def _post_edit_identity(config, ref) -> dict:
    """Post-edit projected identity for the response. The id lookup wins for
    blocks carrying ``lf_txn_id`` (stable across edits and re-ordering); the
    ``txn_order`` fallback recovers ephemeral-id blocks after in-place edits."""
    updated = find_projected_transaction(config, ref.id) or find_projected_transaction_at(
        config, ref.journal_file_id, ref.txn_order
    )
    return {
        "txnId": updated.id if updated else ref.id,
        "blockHash": updated.raw_block_hash if updated else None,
    }


@app.post("/api/transactions/toggle-status")
def transactions_toggle_status(req: ToggleStatusRequest) -> dict:
    """Stable-identity mutation contract (spec: Mutation-Time Projection):
    locate the block by ``lf_txn_id``, reject as stale only when the block
    hash differs, re-project the touched file, return updated projected data.
    """
    config = _require_workspace_config()
    ref = _locate_projected_transaction(config, req.txnId, req.blockHash)

    parsed = parse_header(ref.raw_header)
    if parsed is None:
        raise HTTPException(status_code=400, detail="Invalid header line")

    next_status = _STATUS_CYCLE[parsed.status]
    new_line = set_header_status(ref.raw_header, next_status)

    if not _HEADER_RE.match(new_line):
        raise HTTPException(status_code=500, detail="Rewritten header is invalid")

    journal_path = config.root_dir / ref.journal_path
    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="toggle-status",
        event_type="transaction.status_toggled.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        header_idx = ref.source_start_line - 1
        if header_idx >= len(lines) or lines[header_idx] != ref.raw_header:
            raise HTTPException(status_code=409, detail=_STALE_TRANSACTION_DETAIL)

        lines[header_idx] = new_line
        journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Toggled status to {next_status.value}: {ref.raw_header[:60]}"
        mut.payload = {
            "journal_path": ref.journal_path,
            "header_line": ref.raw_header,
            "previous_status": parsed.status.value,
            "new_status": next_status.value,
            "txn_id": ref.id,
        }

    # The writer re-projected the touched file; just re-read the row.
    return {
        "newStatus": next_status.value,
        **_post_edit_identity(config, ref),
        "eventId": mut.event_id,
    }


# ---------------------------------------------------------------------------
# Transaction actions: delete, re-categorize, unmatch
# ---------------------------------------------------------------------------


def _stale_block_guard(lines: list[str], ref) -> int:
    """Belt-and-suspenders re-check inside the writer block: the projected
    header must still sit at the projected line. Returns the header index."""
    header_idx = ref.source_start_line - 1
    if header_idx >= len(lines) or lines[header_idx] != ref.raw_header:
        raise HTTPException(status_code=409, detail=_STALE_TRANSACTION_DETAIL)
    return header_idx


@app.post("/api/transactions/delete")
def transactions_delete(req: DeleteTransactionRequest) -> dict:
    config = _require_workspace_config()
    ref = _locate_projected_transaction(config, req.txnId, req.blockHash)
    journal_path = config.root_dir / ref.journal_path

    parsed = parse_header(ref.raw_header)
    payee = parsed.payee if parsed else ref.raw_header[:60]
    date_str = parsed.date if parsed else ""

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="delete",
        event_type="transaction.deleted.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = _stale_block_guard(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)
        deleted_block = "\n".join(lines[block_start:block_end])

        # Also consume a preceding blank line to avoid double-blank-line gaps.
        remove_start = block_start
        if remove_start > 0 and lines[remove_start - 1].strip() == "":
            remove_start -= 1
        new_lines = lines[:remove_start] + lines[block_end:]
        journal_path.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Deleted transaction: {payee} on {date_str}"
        mut.payload = {
            "journal_path": ref.journal_path,
            "header_line": ref.raw_header,
            "txn_id": ref.id,
            "deleted_block": deleted_block,
        }

    return {"success": True, "eventId": mut.event_id}


@app.post("/api/transactions/recategorize")
def transactions_recategorize(req: RecategorizeTransactionRequest) -> dict:
    config = _require_workspace_config()
    ref = _locate_projected_transaction(config, req.txnId, req.blockHash)
    journal_path = config.root_dir / ref.journal_path

    parsed = parse_header(ref.raw_header)
    payee = parsed.payee if parsed else ref.raw_header[:60]
    date_str = parsed.date if parsed else ""

    # Collect tracked account ledger names for distinguishing categories from
    # tracked accounts (transfers).
    tracked_ledger_accounts: set[str] = set()
    for ta in config.tracked_accounts.values():
        la = str(ta.get("ledger_account", "")).strip()
        if la:
            tracked_ledger_accounts.add(la)

    previous_account: str | None = None
    target_account: str = ""

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="recategorize",
        event_type="transaction.recategorized.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = _stale_block_guard(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)

        # Find the single destination posting to rewrite.
        destination_idx: int | None = None
        for i in range(block_start + 1, block_end):
            line = lines[i]
            # Skip metadata comments and blank lines.
            stripped = line.strip()
            if stripped.startswith(";") or stripped == "":
                continue
            # Parse the posting account.
            m = ACCOUNT_LINE_RE.match(line) or ACCOUNT_ONLY_RE.match(line)
            if m:
                account = m.group(2).strip()
                if account in tracked_ledger_accounts:
                    continue  # Source (tracked) account — skip.
                if account == "Expenses:Unknown" and not (req.newCategory and req.newCategory.strip()):
                    raise HTTPException(status_code=422, detail="Transaction is already uncategorized")
                if destination_idx is not None:
                    # Multiple non-source postings — split transaction, not supported.
                    raise HTTPException(status_code=422, detail="Cannot re-categorize a split transaction")
                destination_idx = i
                previous_account = account

        if destination_idx is None:
            raise HTTPException(status_code=422, detail="Cannot re-categorize a transfer")

        target_account = req.newCategory.strip() if req.newCategory and req.newCategory.strip() else "Expenses:Unknown"

        if previous_account == target_account:
            raise HTTPException(status_code=422, detail="Transaction already has this category")

        new_line, changed = rewrite_posting_account(lines[destination_idx], target_account)
        if not changed:
            raise HTTPException(status_code=500, detail="Failed to rewrite posting account")
        lines[destination_idx] = new_line

        journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Recategorized: {payee} on {date_str} ({previous_account} → {target_account})"
        mut.payload = {
            "journal_path": ref.journal_path,
            "header_line": ref.raw_header,
            "txn_id": ref.id,
            "previous_account": previous_account,
            "new_account": target_account,
        }

    return {
        "success": True,
        "previousAccount": previous_account,
        "newAccount": target_account,
        **_post_edit_identity(config, ref),
        "eventId": mut.event_id,
    }


# ---------------------------------------------------------------------------
# Reassign account (source posting)
# ---------------------------------------------------------------------------


@app.post("/api/transactions/reassign-account")
def transactions_reassign_account(req: ReassignAccountRequest) -> dict:
    config = _require_workspace_config()

    # Collect tracked account ledger names.
    tracked_ledger_accounts: set[str] = set()
    for ta in config.tracked_accounts.values():
        la = str(ta.get("ledger_account", "")).strip()
        if la:
            tracked_ledger_accounts.add(la)

    if req.newAccountLedgerName not in tracked_ledger_accounts:
        raise HTTPException(status_code=422, detail="Not a tracked account")

    ref = _locate_projected_transaction(config, req.txnId, req.blockHash)
    journal_path = config.root_dir / ref.journal_path

    parsed = parse_header(ref.raw_header)
    payee = parsed.payee if parsed else ref.raw_header[:60]
    date_str = parsed.date if parsed else ""

    previous_account: str | None = None

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="reassign-account",
        event_type="transaction.account_reassigned.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = _stale_block_guard(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)

        # Find the single source (tracked) posting to rewrite.
        source_idx: int | None = None
        for i in range(block_start + 1, block_end):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith(";") or stripped == "":
                continue
            m = ACCOUNT_LINE_RE.match(line) or ACCOUNT_ONLY_RE.match(line)
            if m:
                account = m.group(2).strip()
                if account not in tracked_ledger_accounts:
                    continue  # Destination (category) posting — skip.
                if source_idx is not None:
                    raise HTTPException(status_code=422, detail="Cannot reassign a multi-account transaction")
                source_idx = i
                previous_account = account

        if source_idx is None:
            raise HTTPException(status_code=422, detail="Cannot reassign account on this transaction")

        if previous_account == req.newAccountLedgerName:
            raise HTTPException(status_code=422, detail="Transaction already belongs to this account")

        new_line, changed = rewrite_posting_account(lines[source_idx], req.newAccountLedgerName)
        if not changed:
            raise HTTPException(status_code=500, detail="Failed to rewrite posting account")
        lines[source_idx] = new_line

        journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Reassigned account: {payee} on {date_str} ({previous_account} → {req.newAccountLedgerName})"
        mut.payload = {
            "journal_path": ref.journal_path,
            "header_line": ref.raw_header,
            "txn_id": ref.id,
            "previous_account": previous_account,
            "new_account": req.newAccountLedgerName,
        }

    return {
        "success": True,
        "previousAccount": previous_account,
        "newAccount": req.newAccountLedgerName,
        **_post_edit_identity(config, ref),
        "eventId": mut.event_id,
    }


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

_NOTES_RE = re.compile(r"^(\s*;\s*)notes:\s*(.*)$")


@app.post("/api/transactions/notes")
def transactions_notes(req: UpdateNotesRequest) -> dict:
    config = _require_workspace_config()
    ref = _locate_projected_transaction(config, req.txnId, req.blockHash)
    journal_path = config.root_dir / ref.journal_path

    parsed = parse_header(ref.raw_header)
    payee = parsed.payee if parsed else ref.raw_header[:60]
    date_str = parsed.date if parsed else ""

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="notes",
        event_type="transaction.notes_updated.v1",
    ) as mut:
        text = journal_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        header_idx = _stale_block_guard(lines, ref)
        block_start, block_end = find_transaction_block(lines, header_idx)

        # Find existing notes line within the block and capture its prior value.
        notes_idx: int | None = None
        previous_notes = ""
        for i in range(block_start + 1, block_end):
            m = _NOTES_RE.match(lines[i])
            if m:
                notes_idx = i
                previous_notes = m.group(2).strip()
                break

        if req.notes:
            new_notes_line = f"    ; notes: {req.notes}"
            if notes_idx is not None:
                lines[notes_idx] = new_notes_line
            else:
                # Insert after the header line.
                lines.insert(block_start + 1, new_notes_line)
        else:
            # Empty notes — remove the line if it exists.
            if notes_idx is not None:
                del lines[notes_idx]

        journal_path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")

        mut.summary = f"Notes updated: {payee} on {date_str}"
        mut.payload = {
            "journal_path": ref.journal_path,
            "header_line": ref.raw_header,
            "txn_id": ref.id,
            "notes": req.notes,
            "previous_notes": previous_notes,
        }

    return {"success": True, **_post_edit_identity(config, ref), "eventId": mut.event_id}


@app.post("/api/transactions/unmatch")
def transactions_unmatch(req: UnmatchTransactionRequest) -> dict:
    config = _require_workspace_config()
    ref = _locate_projected_transaction(config, req.txnId, req.blockHash)
    journal_path = config.root_dir / ref.journal_path

    archive_path = config.root_dir / "journals" / "archived-manual.journal"
    if not archive_path.is_file():
        raise HTTPException(status_code=404, detail="No archived entries exist")

    tracked_ledger_accounts: set[str] = set()
    for ta in config.tracked_accounts.values():
        la = str(ta.get("ledger_account", "")).strip()
        if la:
            tracked_ledger_accounts.add(la)

    parsed = parse_header(ref.raw_header)
    payee = parsed.payee if parsed else ref.raw_header[:60]
    date_str = parsed.date if parsed else ""

    with journal_writer.mutate(
        config=config,
        paths=[journal_path, archive_path],
        tag="unmatch",
        event_type="transaction.unmatched.v1",
    ) as mut:
        # --- Locate the archived manual entry by match-id ---
        archive_text = archive_path.read_text(encoding="utf-8")
        archive_lines = archive_text.splitlines()
        archived_block_start: int | None = None
        archived_block_end: int | None = None

        for i, line in enumerate(archive_lines):
            stripped = line.strip()
            if stripped == f"; match-id: {req.matchId}":
                # The match-id tag is on line 2 of the block (header is the previous line).
                if i == 0 or not TXN_START_RE.match(archive_lines[i - 1]):
                    continue
                archived_block_start = i - 1
                # Find end of this block.
                archived_block_end = i + 1
                while archived_block_end < len(archive_lines):
                    if TXN_START_RE.match(archive_lines[archived_block_end]):
                        break
                    archived_block_end += 1
                # Trim trailing blank lines.
                while archived_block_end > archived_block_start + 1 and archive_lines[archived_block_end - 1].strip() == "":
                    archived_block_end -= 1
                break

        if archived_block_start is None:
            raise HTTPException(status_code=404, detail="Archived manual entry not found for this match")

        archived_block_lines = archive_lines[archived_block_start:archived_block_end]

        # --- Modify the main journal: remove :manual: and match-id: tags,
        #     rewrite destination to Expenses:Unknown ---
        main_text = journal_path.read_text(encoding="utf-8")
        main_lines = main_text.splitlines()
        header_idx = _stale_block_guard(main_lines, ref)
        block_start, block_end = find_transaction_block(main_lines, header_idx)

        lines_to_remove: list[int] = []
        destination_idx: int | None = None
        for i in range(block_start + 1, block_end):
            stripped = main_lines[i].strip()
            if stripped == "; :manual:":
                lines_to_remove.append(i)
            elif stripped == f"; match-id: {req.matchId}":
                lines_to_remove.append(i)
            elif not stripped.startswith(";") and stripped != "":
                m = ACCOUNT_LINE_RE.match(main_lines[i]) or ACCOUNT_ONLY_RE.match(main_lines[i])
                if m:
                    account = m.group(2).strip()
                    if account not in tracked_ledger_accounts and destination_idx is None:
                        destination_idx = i

        # Remove tag lines in reverse order to preserve indices.
        for idx in sorted(lines_to_remove, reverse=True):
            del main_lines[idx]

        # Adjust destination_idx for removed lines above it.
        if destination_idx is not None:
            removed_above = sum(1 for idx in lines_to_remove if idx < destination_idx)
            destination_idx -= removed_above
            new_line, _ = rewrite_posting_account(main_lines[destination_idx], "Expenses:Unknown")
            main_lines[destination_idx] = new_line

        journal_path.write_text(
            "\n".join(main_lines) + ("\n" if main_text.endswith("\n") else ""),
            encoding="utf-8",
        )

        # --- Prepare the restored manual entry (strip the match-id tag) ---
        restored_lines: list[str] = []
        for line in archived_block_lines:
            stripped = line.strip()
            if stripped == f"; match-id: {req.matchId}":
                continue
            restored_lines.append(line)
        restored_block = "\n".join(restored_lines)

        # --- Insert restored manual entry into main journal in date order ---
        # Re-read after the first write.
        main_text2 = journal_path.read_text(encoding="utf-8")
        main_lines2 = main_text2.splitlines()

        # Parse the date from the restored entry header.
        restored_date = ""
        if restored_lines and TXN_START_RE.match(restored_lines[0]):
            restored_date = restored_lines[0][:10]

        # Find insertion point: after the last transaction with date <= restored_date.
        insert_idx = len(main_lines2)
        for i in range(len(main_lines2) - 1, -1, -1):
            if TXN_START_RE.match(main_lines2[i]) and main_lines2[i][:10] <= restored_date:
                # Find end of this block to insert after it.
                end_i = i + 1
                while end_i < len(main_lines2):
                    if TXN_START_RE.match(main_lines2[end_i]):
                        break
                    end_i += 1
                insert_idx = end_i
                break

        # Insert with a blank line separator.
        insert_block = [""] + restored_lines if insert_idx > 0 else restored_lines
        main_lines2[insert_idx:insert_idx] = insert_block

        journal_path.write_text(
            "\n".join(main_lines2) + ("\n" if main_text2.endswith("\n") else ""),
            encoding="utf-8",
        )

        # --- Remove the archived block from the archive journal ---
        # Also remove any trailing blank line that separated this block from the next.
        remove_end = archived_block_end
        while remove_end < len(archive_lines) and archive_lines[remove_end].strip() == "":
            remove_end += 1
        # If removing from the beginning, also remove leading blank line of next block.
        new_archive_lines = archive_lines[:archived_block_start] + archive_lines[remove_end:]

        # Clean up: if only the header comment remains, remove the file entirely.
        non_empty = [l for l in new_archive_lines if l.strip() and not l.strip().startswith(";")]
        if non_empty:
            archive_path.write_text(
                "\n".join(new_archive_lines) + ("\n" if archive_text.endswith("\n") else ""),
                encoding="utf-8",
            )
        else:
            archive_path.unlink(missing_ok=True)

        mut.summary = f"Unmatched: {payee} on {date_str} (match-id: {req.matchId})"
        mut.payload = {
            "journal_path": ref.journal_path,
            "archive_path": rel_path(archive_path, config.root_dir),
            "header_line": ref.raw_header,
            "txn_id": ref.id,
            "match_id": req.matchId,
            "restored_manual_block": restored_block,
        }

    return {"success": True, **_post_edit_identity(config, ref), "eventId": mut.event_id}


# ---------------------------------------------------------------------------
# Category suggestion
# ---------------------------------------------------------------------------


@app.get("/api/categories/suggest")
def categories_suggest(payee: str = "") -> dict:
    if not payee.strip():
        return {"suggestion": None, "confidence": 0, "source": None, "alternatives": []}
    config = _require_workspace_config()
    return suggest_category(payee.strip(), config)


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

_UNDO_STATUS_MAP = {
    UndoOutcome.SUCCESS: 200,
    UndoOutcome.ALREADY_COMPENSATED: 200,
    UndoOutcome.NOT_FOUND: 404,
    UndoOutcome.DRIFT: 409,
    UndoOutcome.UNSUPPORTED: 422,
    UndoOutcome.FAILED: 422,
}


_RECENT_EVENTS_LIMIT = 20


@app.get("/api/events")
def events_recent() -> dict:
    """Return the most recent forward + compensating events, newest-first."""
    config = _require_workspace_config()
    events = _read_events_log(config.root_dir)
    window = events[-_RECENT_EVENTS_LIMIT:]

    # A forward event in the window can only be compensated by something that
    # appears later in the log — and since the window is the contiguous tail,
    # any compensator must also be inside the window.
    compensated_by: dict[str, str] = {}
    for ev in window:
        target = ev.get("compensates")
        eid = ev.get("id")
        if target and isinstance(eid, str):
            compensated_by[target] = eid

    rows: list[dict] = []
    for ev in reversed(window):
        eid = ev.get("id", "")
        etype = ev.get("type", "")
        compensating_id = compensated_by.get(eid)
        rows.append({
            "id": eid,
            "type": etype,
            "summary": ev.get("summary", ""),
            "timestamp": ev.get("ts", ""),
            "undoable": is_undoable_type(etype),
            "compensated": compensating_id is not None,
            "compensatedBy": compensating_id,
        })

    return {"events": rows}


@app.post("/api/events/undo/{event_id}")
def events_undo(event_id: str) -> dict:
    config = _require_workspace_config()
    result = undo_event(config, event_id)
    status = _UNDO_STATUS_MAP.get(result.outcome, 500)
    if status >= 400:
        raise HTTPException(
            status_code=status,
            detail={
                "outcome": result.outcome.value,
                "message": result.message,
                "forwardEventId": result.forward_event_id,
            },
        )
    return {
        "outcome": result.outcome.value,
        "message": result.message,
        "compensatingEventId": result.compensating_event_id,
        "forwardEventId": result.forward_event_id,
    }


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
            minimum_payment=req.minimumPayment,
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
            minimum_payment=req.minimumPayment,
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
    reconciliation_status_map = compute_reconciliation_status(config)
    last_reconciled_map = latest_reconciliation_dates_by_tracked_id(config)
    txn_counts = _transaction_counts_by_ledger_account(config)
    subtype_map = _projected_subtypes(config)
    rows = []
    for account_id, account_cfg in config.tracked_accounts.items():
        row = _tracked_account_ui(config, account_id, account_cfg, opening_by_id, opening_by_ledger, reconciliation_status_map, last_reconciled_map, subtype_map)
        ledger_acct = str(account_cfg.get("ledger_account", "")).strip()
        row["transactionCount"] = txn_counts.get(ledger_acct, 0)
        rows.append(row)
    rows.sort(key=lambda r: (-r["transactionCount"], r["displayName"]))
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
            minimum_payment=req.minimumPayment,
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


@app.post("/api/accounts/{account_id}/reconcile")
def accounts_reconcile(account_id: str, req: ReconcileRequest) -> dict:
    config = _require_workspace_config()

    tracked_account_cfg = config.tracked_accounts.get(account_id)
    if tracked_account_cfg is None:
        raise HTTPException(status_code=404, detail=f"Tracked account not found: {account_id}")

    ledger_account = str(tracked_account_cfg.get("ledger_account", "")).strip()
    if not ledger_account:
        raise HTTPException(status_code=400, detail="Tracked account is missing a ledger account.")

    if _account_kind(ledger_account) not in {"asset", "liability"}:
        raise HTTPException(
            status_code=400,
            detail="Reconciliation is only supported for asset and liability accounts.",
        )

    base_currency = str(config.workspace.get("base_currency", "USD")).strip().upper()
    if (req.currency or "").strip().upper() != base_currency:
        raise HTTPException(
            status_code=400,
            detail="Multi-currency accounts are out of scope (#TODO multi-currency support).",
        )

    try:
        period_start = date.fromisoformat(req.periodStart)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid period: {exc}") from exc
    try:
        period_end = date.fromisoformat(req.periodEnd)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid period: {exc}") from exc
    if period_start > period_end:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period: periodStart {req.periodStart} is after periodEnd {req.periodEnd}",
        )

    try:
        closing_balance = parse_closing_balance(req.closingBalance)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid closing balance: {req.closingBalance}") from exc

    existing_latest = latest_reconciliation_date(config, ledger_account)
    if existing_latest is not None:
        if period_end < existing_latest:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A more recent reconciliation already exists for this account on "
                    f"{existing_latest.isoformat()}. Delete it first if you want to "
                    "reconcile an earlier period."
                ),
            )
        if period_end == existing_latest:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A reconciliation already exists for this account on "
                    f"{existing_latest.isoformat()}."
                ),
            )

    year = f"{period_end.year:04d}"
    target_journal_path = config.journal_dir / f"{year}.journal"

    try:
        with journal_writer.mutate(
            config=config,
            paths=[target_journal_path],
            tag="reconcile",
            event_type="account.reconciled.v1",
            verify=lambda cfg, _paths: verify_assertion(cfg),
        ) as mut:
            try:
                write_result = write_assertion_transaction(
                    config=config,
                    tracked_account_cfg=tracked_account_cfg,
                    period_start=period_start,
                    period_end=period_end,
                    closing_balance=closing_balance,
                    currency=base_currency,
                    event_id=mut.event_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            mut.summary = (
                f"Reconciled {tracked_account_cfg.get('display_name', account_id)} · "
                f"ending {period_end.isoformat()} · {req.closingBalance}"
            )
            mut.payload = {
                "tracked_account_id": account_id,
                "ledger_account": ledger_account,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "closing_balance": str(closing_balance),
                "currency": base_currency,
                "journal_path": write_result.journal_rel,
                "header_line": write_result.header_line,
                "line_number": write_result.line_number,
            }
    except journal_writer.WriterRejected as exc:
        failure = exc.failure
        message = (
            f"Reconciliation rejected — expected {failure.expected}, found {failure.actual}."
            if failure.expected and failure.actual
            else "Reconciliation rejected — balance assertion failed."
        )
        raise HTTPException(
            status_code=422,
            detail={
                "outcome": "assertion_failed",
                "message": message,
                "expected": failure.expected,
                "actual": failure.actual,
                "rawError": failure.raw_error,
            },
        ) from exc
    except journal_writer.WriterUnavailable as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not verify the assertion: ledger CLI is unavailable.",
        ) from exc

    # The writer re-projected the touched file; return the assertion block's
    # durable identity so follow-up mutations need no positional data.
    assertion_ref = find_projected_transaction(config, write_result.txn_id)
    return {
        "ok": True,
        "assertionTransaction": {
            "txnId": write_result.txn_id,
            "blockHash": assertion_ref.raw_block_hash if assertion_ref else None,
            "headerLine": write_result.header_line,
        },
        "eventId": mut.event_id,
    }


@app.get("/api/accounts/{account_id}/reconciliation-context")
def accounts_reconciliation_context(
    account_id: str,
    period_start: str,
    period_end: str,
) -> dict:
    config = _require_workspace_config()

    tracked_account_cfg = config.tracked_accounts.get(account_id)
    if tracked_account_cfg is None:
        raise HTTPException(status_code=404, detail=f"Tracked account not found: {account_id}")

    ledger_account = str(tracked_account_cfg.get("ledger_account", "")).strip()
    if not ledger_account:
        raise HTTPException(status_code=400, detail="Tracked account is missing a ledger account.")

    if _account_kind(ledger_account) not in {"asset", "liability"}:
        raise HTTPException(
            status_code=400,
            detail="Reconciliation is only supported for asset and liability accounts.",
        )

    try:
        start = date.fromisoformat(period_start)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid period_start: {exc}") from exc
    try:
        end = date.fromisoformat(period_end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid period_end: {exc}") from exc
    if start > end:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period: period_start {period_start} is after period_end {period_end}",
        )

    try:
        context = build_reconciliation_context(
            config=config,
            tracked_account_cfg=tracked_account_cfg,
            period_start=start,
            period_end=end,
        )
    except CommodityMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "openingBalance": str(context.opening_balance),
        "currency": context.currency,
        "lastReconciliationDate": context.last_reconciliation_date.isoformat()
            if context.last_reconciliation_date is not None
            else None,
        "earliestPostingDate": context.earliest_posting_date.isoformat()
            if context.earliest_posting_date is not None
            else None,
        "transactions": [
            {
                "id": row.id,
                "selectionKey": row.selection_key,
                "date": row.date,
                "payee": row.payee,
                "category": row.category,
                "signedAmount": str(row.signed_amount),
                "sourceLabel": row.source_label,
                "isImported": row.is_imported,
                "isManual": row.is_manual,
                "txnId": row.txn_id,
                "blockHash": row.block_hash,
                "canDelete": row.can_delete,
            }
            for row in context.transactions
        ],
    }


@app.post("/api/accounts/{account_id}/reconciliation-duplicate-review")
def accounts_reconciliation_duplicate_review(
    account_id: str,
    req: ReconciliationDuplicateReviewRequest,
) -> dict:
    config = _require_workspace_config()
    try:
        start = date.fromisoformat(req.periodStart)
        end = date.fromisoformat(req.periodEnd)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid reconciliation review period: {exc}") from exc
    if start > end:
        raise HTTPException(status_code=400, detail="Invalid reconciliation review period.")

    context, groups = build_duplicate_review_payload(
        config=config,
        tracked_account_id=account_id,
        period_start=start,
        period_end=end,
        checked_selection_keys=set(req.checkedSelectionKeys),
    )

    def serialize_row(row) -> dict:
        return {
            "id": row.id,
            "selectionKey": row.selection_key,
            "date": row.date,
            "payee": row.payee,
            "category": row.category,
            "signedAmount": str(row.signed_amount),
            "sourceLabel": row.source_label,
            "isImported": row.is_imported,
            "isManual": row.is_manual,
            "txnId": row.txn_id,
            "blockHash": row.block_hash,
            "canDelete": row.can_delete,
        }

    return {
        "hasGroups": bool(groups),
        "groups": [
            {
                "checked": serialize_row(group["checked"]),
                "matches": [
                    {
                        "row": serialize_row(candidate.row),
                        "reason": candidate.reason,
                        "confidence": candidate.confidence,
                        "action": candidate.action,
                        "actionLabel": candidate.action_label,
                        "actionBlockedReason": candidate.action_blocked_reason,
                    }
                    for candidate in group["matches"]
                ],
            }
            for group in groups
        ],
        "transactionCount": len(context.transactions),
    }


@app.post("/api/accounts/{account_id}/reconciliation-duplicate-resolution")
def accounts_reconciliation_duplicate_resolution(
    account_id: str,
    req: ReconciliationDuplicateResolutionRequest,
) -> dict:
    config = _require_workspace_config()
    try:
        start = date.fromisoformat(req.periodStart)
        end = date.fromisoformat(req.periodEnd)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid reconciliation resolution period: {exc}") from exc
    if start > end:
        raise HTTPException(status_code=400, detail="Invalid reconciliation resolution period.")

    context, groups = build_duplicate_review_payload(
        config=config,
        tracked_account_id=account_id,
        period_start=start,
        period_end=end,
        checked_selection_keys={req.checkedSelectionKey},
    )
    checked_row = next((row for row in context.transactions if row.selection_key == req.checkedSelectionKey), None)
    unchecked_row = next((row for row in context.transactions if row.selection_key == req.uncheckedSelectionKey), None)
    if checked_row is None or unchecked_row is None:
        raise HTTPException(status_code=404, detail="Duplicate review selection is no longer available.")

    match_allowed = False
    for group in groups:
        if group["checked"].selection_key != checked_row.selection_key:
            continue
        for candidate in group["matches"]:
            if candidate.row.selection_key == unchecked_row.selection_key and candidate.action == req.action:
                match_allowed = True
                break
    if not match_allowed:
        raise HTTPException(status_code=422, detail="This duplicate action is no longer available.")

    result = resolve_duplicate_candidate(
        config=config,
        tracked_account_id=account_id,
        checked_row=checked_row,
        unchecked_row=unchecked_row,
        action=req.action,
    )
    return {
        "ok": True,
        "removedSelectionKeys": result["removedSelectionKeys"],
        "addedCheckedSelectionKeys": result["addedCheckedSelectionKeys"],
        "eventId": result.get("eventId"),
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
        dr = row.get("date_range")
        row["date_range"] = {"start": dr[0], "end": dr[1]} if dr else None
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
            **_import_stage_payload(config, str(dest.resolve()), year, importAccountId, data),
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
    category_accounts = list_category_account_names(config)
    return {
        "accounts": category_accounts,
        "categoryAccounts": category_accounts,
        "allAccounts": list_account_names(config),
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
        account_name = _compose_account_name(req)
        added, warning = create_account(
            accounts_dat, account_name, req.accountType, req.description
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if added:
        refresh_projection(config)
    return {"added": added, "warning": warning, "account": account_name}


@app.get("/api/accounts/manage")
def accounts_manage() -> dict:
    """Lifecycle panel rows: every projected account with declared/used/
    closed state, subtree posting counts, and the delete-guard verdict."""
    config = _require_workspace_config()
    rows = []
    for account in list_managed_accounts(config):
        reason = (
            delete_block_reason(config, account["name"], account["posting_count"])
            if account["declared"]
            else None
        )
        rows.append(
            {
                "name": account["name"],
                "accountType": account["account_type"],
                "depth": account["depth"],
                "subtype": account["subtype"],
                "note": account["note"],
                "closedOn": account["closed_on"],
                "declared": account["declared"],
                "used": account["used"],
                "postingCount": account["posting_count"],
                "deletable": account["declared"] and reason is None,
                "deleteBlockedReason": reason,
            }
        )
    return {"accounts": rows}


@app.post("/api/accounts/subtype")
def accounts_set_subtype(req: AccountSubtypeRequest) -> dict:
    config = _require_workspace_config()
    account = req.account.strip()
    if not account:
        raise HTTPException(status_code=400, detail="Account is required")
    if req.subtype is not None:
        expected_kind = ACCOUNT_SUBTYPE_KIND[req.subtype]
        if _account_kind(account) != expected_kind:
            raise HTTPException(
                status_code=400,
                detail=f"Subtype '{req.subtype}' requires a {expected_kind} account",
            )
    set_subtype(config, account, req.subtype)
    return {"ok": True, "account": account, "subtype": req.subtype}


@app.post("/api/accounts/close")
def accounts_close(req: AccountCloseRequest) -> dict:
    config = _require_workspace_config()
    account = req.account.strip()
    if not account:
        raise HTTPException(status_code=400, detail="Account is required")
    closed_on = (req.closedOn or "").strip() or date.today().isoformat()
    try:
        date.fromisoformat(closed_on)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid close date: {closed_on}"
        ) from e
    close_account(config, account, closed_on)
    return {"ok": True, "account": account, "closedOn": closed_on}


@app.post("/api/accounts/reopen")
def accounts_reopen(req: AccountNameRequest) -> dict:
    config = _require_workspace_config()
    account = req.account.strip()
    if not account:
        raise HTTPException(status_code=400, detail="Account is required")
    reopen_account(config, account)
    return {"ok": True, "account": account}


@app.post("/api/accounts/delete")
def accounts_delete(req: AccountNameRequest) -> dict:
    config = _require_workspace_config()
    account = req.account.strip()
    if not account:
        raise HTTPException(status_code=400, detail="Account is required")
    try:
        delete_declaration(config, account)
    except DeclarationInUse as e:
        raise HTTPException(status_code=409, detail=e.reason) from e
    except AccountNotDeclared as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True, "account": account}


def _compose_account_name(req: CreateAccountRequest) -> str:
    """Parent + leaf from the picker flow, or the legacy fully qualified name."""
    if req.parent is not None or req.leaf is not None:
        parent = (req.parent or "").strip()
        leaf = (req.leaf or "").strip()
        if not parent:
            raise ValueError("Parent account is required")
        if not leaf:
            raise ValueError("Account name is required")
        if ":" in leaf:
            raise ValueError("Account name cannot contain ':'")
        return f"{parent}:{leaf}"
    if req.account is None or not req.account.strip():
        raise ValueError("Account is required")
    return req.account.strip()


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

    return _import_stage_payload(config, req.csvPath, req.year, req.importAccountId, data)


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
    stages = StageStore(config)
    try:
        stage = stages.load(req.stageId)
    except StageNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e

    if stage.get("kind") != "import":
        raise HTTPException(status_code=400, detail="stage kind mismatch")
    if stage.get("status") == "applied":
        return stage

    journal = Path(stage["targetJournalPath"])

    with journal_writer.mutate(
        config=config,
        paths=[journal],
        tag="import",
        event_type="import.applied.v1",
    ) as mut:
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
            "backupPath": None,
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

        source_file = Path(stage.get("csvPath", "")).name
        mut.summary = f"Imported {appended_count} transactions from {source_file}"
        mut.payload = {
            "journal_path": rel_path(journal, config.root_dir),
            "source_file": source_file,
            "account_id": stage.get("importAccountId", ""),
            "transactions_added": appended_count,
            "duplicates_skipped": skipped_duplicate_count,
            "conflicts": conflicts,
            "history_id": history_entry["id"],
        }

    return stage


@app.get("/api/import/history")
def import_history() -> dict:
    config = _require_workspace_config()
    return {"history": list_import_history(config)}


@app.post("/api/import/undo")
def import_undo(req: ImportUndoRequest) -> dict:
    config = _require_workspace_config()

    journal_path: Path | None = None
    for entry_item in list_import_history(config):
        if str(entry_item.get("id")) == req.historyId:
            jp = entry_item.get("targetJournalPath")
            if jp:
                journal_path = Path(str(jp))
            break

    if journal_path is None:
        raise HTTPException(status_code=404, detail="import history entry not found")

    entry: dict = {}
    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="import-undo",
        event_type="import.undone.v1",
    ) as mut:
        try:
            entry = undo_import(config, req.historyId)
        except KeyError as e:
            raise HTTPException(status_code=404, detail="import history entry not found") from e
        except (FileNotFoundError, OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        removed_count = entry.get("undo", {}).get("removedTxnCount", 0)
        mut.summary = f"Undid import {req.historyId}: removed {removed_count} transactions"
        mut.payload = {
            "journal_path": rel_path(journal_path, config.root_dir),
            "history_id": req.historyId,
            "transactions_removed": removed_count,
        }

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
    stages = StageStore(config)
    existing_stage = _find_resumable_unknown_stage(config, journal_path)
    if existing_stage is not None:
        payload = {
            **existing_stage,
            **_build_unknown_stage_payload(journal_path, data["groups"], existing_stage.get("selections")),
            "stageId": existing_stage["stageId"],
        }
        stages.save(existing_stage["stageId"], payload)
        return payload

    payload = _build_unknown_stage_payload(journal_path, data["groups"])
    stage_id = stages.create(payload, base_files=[journal_path.resolve()])
    payload["stageId"] = stage_id
    return payload


@app.post("/api/unknowns/stage-mappings")
def unknown_stage_mappings(req: UnknownStageRequest) -> dict:
    config = _require_workspace_config()
    stages = StageStore(config)
    try:
        stage = stages.load(req.stageId)
    except StageNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e

    if stage.get("kind") != "unknowns":
        raise HTTPException(status_code=400, detail="stage kind mismatch")

    selections = {
        selection.txnId: {
            **selection.model_dump(exclude_none=True),
            "groupKey": _group_key_for_txn(stage.get("groups") or [], selection.txnId),
        }
        for selection in req.selections
    }
    selections = _filtered_unknown_selections(stage.get("groups") or [], selections)
    stage["selections"] = selections
    stage["summary"] = _unknown_stage_summary(stage["groups"], selections)
    stages.save(req.stageId, stage)
    return stage


@app.post("/api/unknowns/apply")
def unknown_apply(req: StageApplyRequest) -> dict:
    config = _require_workspace_config()
    stages = StageStore(config)
    try:
        stage = stages.load(req.stageId)
    except StageNotFoundError as e:
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

    with journal_writer.mutate(
        config=config,
        paths=[journal_path, accounts_dat, archived_manual],
        tag="unknowns",
        event_type="unknowns.applied.v1",
    ) as mut:
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
            "backupPaths": None,
            "updatedTxnCount": txn_updates,
            "warnings": warnings,
        }
        stages.save(req.stageId, stage)

        match_ids = [
            sel.get("matchId") or ""
            for sel in selections.values()
            if sel.get("selectionType") == "match"
        ]
        mappings_applied = sum(1 for sel in selections.values() if sel.get("selectionType") == "category")
        mut.summary = f"Applied {mappings_applied} mappings and {len(match_ids)} matches"
        mut.payload = {
            "journal_path": rel_path(journal_path, config.root_dir),
            "mappings_applied": mappings_applied,
            "matches_applied": len(match_ids),
            "match_ids": match_ids,
            "warnings": warnings,
        }

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
    stage_id = StageStore(config).create(payload, base_files=[journal_path.resolve()])
    payload["stageId"] = stage_id
    return payload


@app.post("/api/rules/history/apply")
def rules_history_apply(req: RuleHistoryApplyRequest) -> dict:
    config = _require_workspace_config()
    stages = StageStore(config)
    try:
        stage = stages.load(req.stageId)
    except StageNotFoundError as e:
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

    with journal_writer.mutate(
        config=config,
        paths=[journal_path],
        tag="rule-history",
        event_type="rule.history_applied.v1",
    ) as mut:
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
            "backupPath": None,
            "updatedTxnCount": updated_count,
            "warnings": warnings,
        }
        stages.save(req.stageId, stage)

        mut.summary = f"Applied rule history: {updated_count} transactions updated"
        mut.payload = {
            "journal_path": rel_path(journal_path, config.root_dir),
            "transactions_updated": updated_count,
            "selected_candidate_count": len(selected_candidate_ids),
            "warnings": warnings,
        }

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
    config = _require_workspace_config()
    try:
        return StageStore(config).load(stage_id)
    except StageNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e


@app.delete("/api/stages/{stage_id}")
def delete_stage(stage_id: str) -> dict:
    config = _require_workspace_config()
    StageStore(config).delete(stage_id)
    return {"deleted": True, "stageId": stage_id}


def _frontend_static_dir() -> Path:
    configured = os.environ.get("LEDGER_FLOW_STATIC_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        return Path(str(resources.files("ledger_flow_frontend").joinpath("static"))).resolve()
    except ModuleNotFoundError:
        return Path(__file__).resolve().parent / "ledger_flow_frontend" / "static"


def _mount_frontend() -> None:
    static_dir = _frontend_static_dir()
    index_path = static_dir / "index.html"
    if not index_path.exists():
        return

    app_assets = static_dir / "_app"
    if app_assets.exists():
        app.mount(
            "/_app",
            StaticFiles(directory=app_assets),
            name="frontend-assets",
        )

    @app.get("/")
    def frontend_index():
        return FileResponse(index_path)

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_fallback(full_path: str):
        requested = static_dir / full_path
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(index_path)


_mount_frontend()
