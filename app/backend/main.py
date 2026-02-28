from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import (
    ImportPreviewRequest,
    StageApplyRequest,
    UnknownScanRequest,
    UnknownStageRequest,
)
from services.backup_service import backup_file
from services.config_service import load_config
from services.import_service import preview_import, scan_candidates, apply_import
from services.ledger_runner import CommandError, run_cmd
from services.stage_store import StageStore
from services.unknowns_service import apply_unknown_mappings, scan_unknowns


ROOT_DIR = Path(__file__).resolve().parents[2]
config = load_config(ROOT_DIR)
stages = StageStore(ROOT_DIR)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stages.cleanup_old(days=7)
    yield


app = FastAPI(title="Ledger Workflow API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    try:
        ledger_version = run_cmd(["ledger", "--version"], ROOT_DIR).splitlines()[0]
        hledger_version = run_cmd(["hledger", "--version"], ROOT_DIR).splitlines()[0]
    except CommandError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "ok", "ledgerVersion": ledger_version, "hledgerVersion": hledger_version}


@app.get("/api/import/candidates")
def import_candidates() -> dict:
    rows = [c.__dict__ for c in scan_candidates(config)]
    return {"candidates": rows, "institutions": sorted(config.institutions.keys())}


@app.post("/api/import/preview")
def import_preview(req: ImportPreviewRequest) -> dict:
    try:
        data = preview_import(config, Path(req.csvPath), req.year, req.institution)
    except (FileNotFoundError, ValueError, CommandError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    payload = {
        "kind": "import",
        "status": "ready",
        "csvPath": req.csvPath,
        "year": req.year,
        "institution": req.institution,
        **data,
    }
    stage_id = stages.create(payload)
    payload["stageId"] = stage_id
    return payload


@app.post("/api/import/apply")
def import_apply(req: StageApplyRequest) -> dict:
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
        journal_path, appended_count = apply_import(config, stage)
    except CommandError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    stage["status"] = "applied"
    stage["result"] = {
        "applied": True,
        "backupPath": str(backup.resolve()) if backup else None,
        "journalPath": journal_path,
        "appendedTxnCount": appended_count,
    }
    stages.save(req.stageId, stage)
    return stage


@app.post("/api/unknowns/scan")
def unknown_scan(req: UnknownScanRequest) -> dict:
    journal_path = Path(req.journalPath)
    if not journal_path.exists():
        raise HTTPException(status_code=404, detail="journal not found")

    accounts_dat = config.init_dir / "10-accounts.dat"
    data = scan_unknowns(journal_path, accounts_dat)
    payload = {
        "kind": "unknowns",
        "status": "ready",
        "journalPath": str(journal_path.resolve()),
        "groups": data["groups"],
        "mappings": {},
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

    mappings = {m.groupKey: m.chosenAccount for m in req.mappings}
    stage["mappings"] = mappings
    stage["summary"] = {
        "groupCount": len(mappings),
        "txnUpdates": sum(len(g["txns"]) for g in stage["groups"] if g["groupKey"] in mappings),
    }
    stages.save(req.stageId, stage)
    return stage


@app.post("/api/unknowns/apply")
def unknown_apply(req: StageApplyRequest) -> dict:
    try:
        stage = stages.load(req.stageId)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="stage not found") from e

    if stage.get("kind") != "unknowns":
        raise HTTPException(status_code=400, detail="stage kind mismatch")
    if stage.get("status") == "applied":
        return stage

    mappings = stage.get("mappings") or {}
    if not mappings:
        raise HTTPException(status_code=400, detail="no mappings staged")

    journal_path = Path(stage["journalPath"])
    accounts_dat = config.init_dir / "10-accounts.dat"
    journal_backup = backup_file(journal_path, "unknowns")
    accounts_backup = backup_file(accounts_dat, "rules")

    txn_updates, rule_adds, warnings = apply_unknown_mappings(
        journal_path=journal_path,
        accounts_dat=accounts_dat,
        mappings=mappings,
        scanned_groups=stage["groups"],
    )

    stage["status"] = "applied"
    stage["result"] = {
        "applied": True,
        "backupPaths": [str(journal_backup.resolve()), str(accounts_backup.resolve())],
        "updatedTxnCount": txn_updates,
        "addedRuleCount": rule_adds,
        "warnings": warnings,
    }
    stages.save(req.stageId, stage)
    return stage


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
