from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import re
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from models import (
    CustomImportAccountUpsertRequest,
    CreateAccountRequest,
    ImportPreviewRequest,
    ImportUndoRequest,
    PayeeRuleRequest,
    RuleHistoryApplyRequest,
    RuleHistoryScanRequest,
    RuleCreateRequest,
    RuleReorderRequest,
    RuleUpdateRequest,
    StageApplyRequest,
    TrackedAccountUpsertRequest,
    UnknownScanRequest,
    UnknownStageRequest,
    WorkspaceImportAccountUpsertRequest,
    WorkspaceBootstrapRequest,
    WorkspaceSelectRequest,
)
from services.backup_service import backup_file
from services.account_register_service import build_account_register
from services.custom_csv_service import inspect_csv_bytes
from services.dashboard_service import build_dashboard_overview
from services.import_history_service import list_import_history, record_applied_import, undo_import
from services.import_index import ImportIndex
from services.import_service import apply_import, archive_inbox_csv, preview_import, scan_candidates
from services.import_profile_service import import_source_summary
from services.institution_registry import canonical_template_id, display_name_for, list_templates
from services.ledger_runner import CommandError, run_cmd
from services.opening_balance_service import opening_balance_index
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
from services.workspace_service import WorkspaceManager


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

    return {
        "id": account_id,
        "displayName": account_cfg.get("display_name", account_id),
        "ledgerAccount": ledger_account,
        "kind": _account_kind(ledger_account),
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
    }


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stages.cleanup_old(days=7)
    import_index.ensure_schema()
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
    return build_dashboard_overview(config)


@app.get("/api/transactions/register")
def transactions_register(accountId: str) -> dict:
    config = _require_workspace_config()
    try:
        return build_account_register(config, accountId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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
                "last4": req.last4,
            },
            account_id=req.accountId,
            opening_balance=req.openingBalance,
            opening_balance_date=req.openingBalanceDate,
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
                "last4": req.last4,
                "customProfile": req.customProfile.model_dump(),
            },
            account_id=req.accountId,
            opening_balance=req.openingBalance,
            opening_balance_date=req.openingBalanceDate,
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
                "institutionId": req.institutionId,
                "last4": req.last4,
            },
            account_id=req.accountId,
            opening_balance=req.openingBalance,
            opening_balance_date=req.openingBalanceDate,
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
    try:
        data = preview_import(
            config,
            Path(req.csvPath),
            req.year,
            req.importAccountId,
        )
    except (FileNotFoundError, ValueError, CommandError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    payload = {
        "kind": "import",
        "status": "ready",
        "csvPath": req.csvPath,
        "year": req.year,
        "importAccountId": req.importAccountId,
        **data,
    }
    stage_id = stages.create(payload)
    payload["stageId"] = stage_id
    return payload


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
    return stage


@app.get("/api/import/history")
def import_history() -> dict:
    config = _require_workspace_config()
    return {"history": list_import_history(config)}


@app.post("/api/import/undo")
def import_undo(req: ImportUndoRequest) -> dict:
    config = _require_workspace_config()
    try:
        entry = undo_import(config, req.historyId)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="import history entry not found") from e
    except (FileNotFoundError, OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
    payload = {
        "kind": "unknowns",
        "status": "ready",
        "journalPath": str(journal_path.resolve()),
        "groups": data["groups"],
        "selections": {},
    }
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
    stage["summary"] = {
        "groupCount": len(selections),
        "txnUpdates": sum(len(g["txns"]) for g in stage["groups"] if g["groupKey"] in selections),
    }
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
