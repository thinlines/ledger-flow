from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class ImportIndex:
    db_path: Path
    table_name: str = "imported_transactions_v2"

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    import_account_id TEXT NOT NULL,
                    source_identity TEXT NOT NULL,
                    source_payload_hash TEXT,
                    journal_path TEXT NOT NULL,
                    year TEXT NOT NULL,
                    source_file_sha256 TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (import_account_id, source_identity)
                )
                """
            )

    def get_identity_map(self, import_account_id: str) -> dict[str, str | None]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT source_identity, source_payload_hash
                FROM {self.table_name}
                WHERE import_account_id = ?
                """,
                (import_account_id,),
            ).fetchall()
        return {identity: payload_hash for identity, payload_hash in rows}

    def upsert_transactions(
        self,
        import_account_id: str,
        year: str,
        journal_path: Path,
        source_file_sha256: str,
        txns: list[dict],
    ) -> None:
        if not txns:
            return
        self.ensure_schema()
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            for txn in txns:
                conn.execute(
                    f"""
                    INSERT INTO {self.table_name} (
                        import_account_id,
                        source_identity,
                        source_payload_hash,
                        journal_path,
                        year,
                        source_file_sha256,
                        first_seen_at,
                        last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(import_account_id, source_identity)
                    DO UPDATE SET
                        source_payload_hash = excluded.source_payload_hash,
                        journal_path = excluded.journal_path,
                        year = excluded.year,
                        source_file_sha256 = excluded.source_file_sha256,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        import_account_id,
                        txn["sourceIdentity"],
                        txn.get("sourcePayloadHash"),
                        str(journal_path),
                        year,
                        source_file_sha256,
                        now,
                        now,
                    ),
                )

    def delete_transactions(self, import_account_id: str, source_identities: list[str]) -> None:
        if not source_identities:
            return
        self.ensure_schema()
        with self._connect() as conn:
            conn.executemany(
                f"""
                DELETE FROM {self.table_name}
                WHERE import_account_id = ? AND source_identity = ?
                """,
                [(import_account_id, source_identity) for source_identity in source_identities],
            )
