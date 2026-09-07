import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from services.config_service import AppConfig  # noqa: E402
from services.workspace_service import ensure_workspace_journal_includes  # noqa: E402


def _build_books_config(workspace: Path) -> AppConfig:
    for rel in ["settings", "journals", "inbox", "rules", "opening", "imports"]:
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    return AppConfig(
        root_dir=workspace,
        config_toml=workspace / "settings" / "workspace.toml",
        workspace={"name": "Test Books", "start_year": 2026, "base_currency": "USD"},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": "rules",
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "last4": "1234",
                "tracked_account_id": "checking",
            },
            "savings": {
                "display_name": "Savings",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Savings",
                "last4": "4321",
                "tracked_account_id": "savings",
            },
            "visa": {
                "display_name": "Visa Signature",
                "institution": "visa",
                "ledger_account": "Liabilities:Cards:Visa",
                "last4": "5678",
                "tracked_account_id": "visa",
            },
        },
        tracked_accounts={
            "checking": {
                "display_name": "Wells Fargo Checking",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Checking",
                "last4": "1234",
                "import_account_id": "checking",
            },
            "visa": {
                "display_name": "Visa Signature",
                "institution": "visa",
                "ledger_account": "Liabilities:Cards:Visa",
                "last4": "5678",
                "import_account_id": "visa",
            },
            "savings": {
                "display_name": "Savings",
                "institution": "wells_fargo",
                "ledger_account": "Assets:Bank:Savings",
                "last4": "4321",
                "import_account_id": "savings",
            },
            "vehicle": {
                "display_name": "Vehicle",
                "ledger_account": "Assets:Vehicle:Subaru",
                "import_account_id": None,
            },
        },
    )


@pytest.fixture
def books_config(tmp_path: Path) -> AppConfig:
    """A workspace with checking, savings, visa, and vehicle tracked accounts."""
    return _build_books_config(tmp_path / "workspace")


def write_year_journal(config: AppConfig, body: str = "") -> None:
    (config.journal_dir / "2026.journal").write_text(body, encoding="utf-8")
    ensure_workspace_journal_includes(config)


def record_event(
    workspace: Path,
    *,
    event_type: str,
    summary: str,
    payload: dict,
    journal_refs: list[dict],
    actor: str = "user",
    compensates: str | None = None,
    event_id: str | None = None,
) -> str:
    """Seed one event-shaped operation for a test workspace."""
    from services.operations_service import record_operation

    op_id = event_id or str(uuid7())
    timestamp = datetime.now(UTC).isoformat()
    return record_operation(
        workspace,
        operation_id=op_id,
        operation_type=event_type,
        summary=summary,
        payload=payload,
        files=journal_refs,
        actor_type=actor,
        compensates_operation_id=compensates,
        created_at=timestamp,
        applied_at=timestamp,
    )


def read_operation_events(workspace: Path) -> list[dict]:
    """Test adapter for assertions that still use the former event shape."""
    db_path = workspace / ".workflow" / "state.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        operations = conn.execute(
            """SELECT id, type, actor_type, summary, created_at,
                      compensates_operation_id, payload_json
               FROM operations ORDER BY created_at, id"""
        ).fetchall()
        files = conn.execute(
            """SELECT operation_id, path, hash_before, hash_after
               FROM operation_files ORDER BY rowid"""
        ).fetchall()
    files_by_operation: dict[str, list[dict]] = {}
    for operation_id, path, hash_before, hash_after in files:
        files_by_operation.setdefault(operation_id, []).append(
            {"path": path, "hash_before": hash_before, "hash_after": hash_after}
        )
    return [
        {
            "id": operation_id,
            "ts": created_at,
            "actor": actor,
            "type": operation_type,
            "summary": summary,
            "payload": json.loads(payload_json or "{}"),
            "journal_refs": files_by_operation.get(operation_id, []),
            "compensates": compensates,
        }
        for operation_id, operation_type, actor, summary, created_at, compensates, payload_json in operations
    ]
