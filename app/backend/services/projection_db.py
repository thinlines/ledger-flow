"""Workspace-scoped SQLite bootstrap for the journal projection.

The projection shares ``.workflow/state.db`` with the import index, resolved
from the workspace config's root. Schema changes are versioned, in-code
migrations recorded in ``schema_migrations``; ``ensure_database`` is the
idempotent entry point every reader/writer goes through.

Table DDL follows docs/ledger-flow-projection-schema.md (Revision 2). Flags
are declared BOOLEAN with TRUE/FALSE literals — SQLite stores 1/0, the
spelling is what Postgres requires. IDs are text throughout.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .config_service import AppConfig

# Projection-class tables: safe to wipe and rebuild from plaintext journals.
PROJECTION_TABLES: tuple[str, ...] = (
    "journal_files",
    "journal_items",
    "transactions",
    "postings",
    "comments",
    "metadata_entries",
    "journal_diagnostics",
    "accounts",
    "payees",
    "payee_aliases",
    "tags",
    "commodities",
)

_MIGRATION_0001 = """
CREATE TABLE IF NOT EXISTS journal_files (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'journal'
        CHECK (role IN ('journal', 'directives', 'opening', 'archive')),
    content_hash TEXT NOT NULL,
    parsed_at TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'ok'
        CHECK (parse_status IN ('ok', 'warning', 'error')),
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT NOT NULL REFERENCES journal_files(id) ON DELETE CASCADE,
    txn_order INTEGER NOT NULL,
    date TEXT NOT NULL,
    effective_date TEXT,
    status TEXT NOT NULL DEFAULT 'unmarked'
        CHECK (status IN ('unmarked', 'pending', 'cleared')),
    code TEXT,
    payee TEXT NOT NULL,
    raw_header TEXT NOT NULL,
    raw_block_hash TEXT NOT NULL,
    source_start_line INTEGER NOT NULL,
    source_end_line INTEGER NOT NULL,
    managed_by_app BOOLEAN NOT NULL DEFAULT FALSE,
    parse_status TEXT NOT NULL DEFAULT 'ok'
        CHECK (parse_status IN ('ok', 'preserved_raw', 'warning', 'error')),
    created_from_operation_id TEXT,
    UNIQUE (journal_file_id, txn_order)
);

CREATE INDEX IF NOT EXISTS transactions_date_idx ON transactions(date);
CREATE INDEX IF NOT EXISTS transactions_payee_idx ON transactions(payee);
CREATE INDEX IF NOT EXISTS transactions_file_line_idx
    ON transactions(journal_file_id, source_start_line);

CREATE TABLE IF NOT EXISTS journal_items (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT NOT NULL REFERENCES journal_files(id) ON DELETE CASCADE,
    item_order INTEGER NOT NULL,
    item_type TEXT NOT NULL
        CHECK (item_type IN (
            'blank',
            'comment',
            'include',
            'directive',
            'transaction',
            'raw'
        )),
    transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
    raw_text TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    source_start_line INTEGER NOT NULL,
    source_end_line INTEGER NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'preserved'
        CHECK (parse_status IN ('managed', 'preserved', 'error')),
    UNIQUE (journal_file_id, item_order)
);

CREATE INDEX IF NOT EXISTS journal_items_file_order_idx
    ON journal_items(journal_file_id, item_order);
CREATE INDEX IF NOT EXISTS journal_items_transaction_idx
    ON journal_items(transaction_id);

CREATE TABLE IF NOT EXISTS postings (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    posting_order INTEGER NOT NULL,
    account TEXT NOT NULL,
    amount_nano INTEGER,
    commodity TEXT,
    amount_inferred BOOLEAN NOT NULL DEFAULT FALSE,
    balance_assertion_text TEXT,
    raw_line TEXT NOT NULL,
    raw_line_hash TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    managed_by_app BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (transaction_id, posting_order)
);

CREATE INDEX IF NOT EXISTS postings_account_idx ON postings(account);
CREATE INDEX IF NOT EXISTS postings_transaction_idx ON postings(transaction_id);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('transaction', 'posting')),
    owner_id TEXT NOT NULL,
    comment_order INTEGER NOT NULL,
    source_location TEXT NOT NULL
        CHECK (source_location IN (
            'header_inline',
            'txn_comment',
            'posting_inline',
            'posting_comment'
        )),
    raw_text TEXT NOT NULL,
    parse_status TEXT NOT NULL DEFAULT 'raw'
        CHECK (parse_status IN ('kv', 'tag', 'raw', 'error')),
    parsed_key TEXT,
    parsed_value_text TEXT
);

CREATE INDEX IF NOT EXISTS comments_owner_idx
    ON comments(owner_type, owner_id, comment_order);
CREATE INDEX IF NOT EXISTS comments_key_idx ON comments(parsed_key);

CREATE TABLE IF NOT EXISTS metadata_entries (
    id TEXT PRIMARY KEY,
    comment_id TEXT NOT NULL UNIQUE REFERENCES comments(id) ON DELETE CASCADE,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('transaction', 'posting')),
    owner_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_text TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'string'
        CHECK (value_type IN (
            'string',
            'date',
            'account',
            'amount',
            'boolean',
            'uuid',
            'json',
            'unknown'
        )),
    value_string TEXT,
    value_date TEXT,
    value_decimal TEXT,
    value_commodity TEXT,
    value_boolean BOOLEAN,
    source_location TEXT NOT NULL,
    source_order INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS metadata_owner_idx
    ON metadata_entries(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS metadata_key_idx ON metadata_entries(key);
CREATE INDEX IF NOT EXISTS metadata_key_value_idx
    ON metadata_entries(key, value_text);

CREATE TABLE IF NOT EXISTS journal_diagnostics (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    line_number INTEGER,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    blocking BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS diagnostics_file_idx
    ON journal_diagnostics(journal_file_id, line_number);
"""

_MIGRATION_0002 = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    account_type TEXT NOT NULL
        CHECK (account_type IN ('assets', 'liabilities', 'income', 'expenses', 'equity', 'other')),
    subtype TEXT,
    parent_name TEXT,
    depth INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    closed_on TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    managed_by_app BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS accounts_type_idx ON accounts(account_type, subtype);
CREATE INDEX IF NOT EXISTS accounts_parent_idx ON accounts(parent_name);

CREATE TABLE IF NOT EXISTS payees (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    default_account TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS payee_aliases (
    id TEXT PRIMARY KEY,
    payee_id TEXT NOT NULL REFERENCES payees(id) ON DELETE CASCADE,
    pattern TEXT NOT NULL,
    alias_order INTEGER NOT NULL,
    UNIQUE (payee_id, pattern)
);

CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    name TEXT NOT NULL UNIQUE,
    note TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS commodities (
    id TEXT PRIMARY KEY,
    journal_file_id TEXT REFERENCES journal_files(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL UNIQUE,
    format TEXT,
    display_scale INTEGER NOT NULL DEFAULT 2,
    note TEXT,
    declared BOOLEAN NOT NULL DEFAULT FALSE,
    used BOOLEAN NOT NULL DEFAULT FALSE
);
"""

# Operation-class and workflow-state tables. Neither is wiped on projection
# rebuild: operations are durable history; stages are resumable in-flight
# workflow state. `operations` ships as DDL only — the stages FK needs the
# parent table to exist (SQLite refuses child-table DML otherwise); #22 wires
# the operations spine. `operation_files` / `operation_entities` arrive with it.
_MIGRATION_0003 = """
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    actor_type TEXT NOT NULL DEFAULT 'user'
        CHECK (actor_type IN ('user', 'system', 'ai')),
    actor_id TEXT,
    status TEXT NOT NULL DEFAULT 'applied'
        CHECK (status IN ('staged', 'applying', 'applied', 'failed', 'undone')),
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    base_revision TEXT,
    git_commit_sha TEXT,
    undo_mode TEXT NOT NULL DEFAULT 'exact'
        CHECK (undo_mode IN ('exact', 'semantic', 'unavailable')),
    compensates_operation_id TEXT REFERENCES operations(id),
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS operations_type_idx ON operations(type);
CREATE INDEX IF NOT EXISTS operations_created_idx ON operations(created_at);
CREATE INDEX IF NOT EXISTS operations_compensates_idx
    ON operations(compensates_operation_id);

CREATE TABLE IF NOT EXISTS stages (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready', 'stale', 'applied', 'discarded', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    base_revision TEXT,
    base_file_hashes_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL,
    applied_operation_id TEXT REFERENCES operations(id) ON DELETE SET NULL
);
"""

_MIGRATION_0004 = """
CREATE TABLE IF NOT EXISTS import_sources (
    id TEXT PRIMARY KEY,
    import_account_id TEXT NOT NULL,
    source_file_sha256 TEXT NOT NULL,
    original_path TEXT,
    archived_path TEXT,
    file_name TEXT NOT NULL,
    imported_at TEXT,
    UNIQUE (import_account_id, source_file_sha256)
);

CREATE TABLE IF NOT EXISTS import_identities (
    id TEXT PRIMARY KEY,
    import_account_id TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    source_payload_hash TEXT,
    transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
    import_source_id TEXT REFERENCES import_sources(id) ON DELETE SET NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    current_status TEXT NOT NULL DEFAULT 'active'
        CHECK (current_status IN ('active', 'undone', 'merged', 'missing')),
    UNIQUE (import_account_id, source_identity)
);

CREATE INDEX IF NOT EXISTS import_identities_txn_idx ON import_identities(transaction_id);
"""

_MIGRATION_0005 = """
CREATE TABLE IF NOT EXISTS operation_files (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    hash_before TEXT NOT NULL,
    hash_after TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS operation_files_operation_idx
    ON operation_files(operation_id);
CREATE INDEX IF NOT EXISTS operation_files_path_idx
    ON operation_files(path);

CREATE TABLE IF NOT EXISTS operation_entities (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'affected',
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS operation_entities_operation_idx
    ON operation_entities(operation_id);
CREATE INDEX IF NOT EXISTS operation_entities_entity_idx
    ON operation_entities(entity_type, entity_id);
"""

MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "journal_projection_tables", _MIGRATION_0001),
    (2, "reference_data_tables", _MIGRATION_0002),
    (3, "operations_and_stages_tables", _MIGRATION_0003),
    (4, "import_identity_tables", _MIGRATION_0004),
    (5, "operation_files_and_entities_tables", _MIGRATION_0005),
)


def database_path(config: AppConfig) -> Path:
    return config.root_dir / ".workflow" / "state.db"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def ensure_database(config: AppConfig) -> Path:
    """Create the workspace database and apply pending migrations. Idempotent."""
    db_path = database_path(config)
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            version
            for (version,) in conn.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        for version, name, ddl in MIGRATIONS:
            if version in applied:
                continue
            conn.executescript(ddl)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now(UTC).isoformat()),
            )
    return db_path
