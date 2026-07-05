from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .config_service import AppConfig
from .projection_db import connect, database_path, ensure_database

from .commodity_service import canonicalize_base_currency_posting


ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
IMPORT_ACCOUNT_PLACEHOLDER = "__IMPORT_ACCOUNT__"


@dataclass(frozen=True)
class ImportIdentityStore:
    config: AppConfig

    def _db_path(self) -> Path:
        ensure_database(self.config)
        return database_path(self.config)

    def get_active_identity_map(self, import_account_id: str) -> dict[str, str | None]:
        with connect(self._db_path()) as conn:
            rows = conn.execute(
                """
                SELECT source_identity, source_payload_hash
                FROM import_identities
                WHERE import_account_id = ?
                  AND current_status != 'undone'
                """,
                (import_account_id,),
            ).fetchall()
        return {identity: payload_hash for identity, payload_hash in rows}

    def get_all_statuses(self, import_account_id: str) -> dict[str, str]:
        with connect(self._db_path()) as conn:
            rows = conn.execute(
                """
                SELECT source_identity, current_status
                FROM import_identities
                WHERE import_account_id = ?
                """,
                (import_account_id,),
            ).fetchall()
        return {identity: status for identity, status in rows}

    def upsert_active(
        self,
        *,
        import_account_id: str,
        source_file_sha256: str,
        original_path: str | Path | None,
        archived_path: str | Path | None,
        file_name: str,
        txns: list[dict],
    ) -> str | None:
        now = datetime.now(UTC).isoformat()
        source_id = None
        with connect(self._db_path()) as conn:
            if source_file_sha256:
                row = conn.execute(
                    """
                    SELECT id
                    FROM import_sources
                    WHERE import_account_id = ? AND source_file_sha256 = ?
                    """,
                    (import_account_id, source_file_sha256),
                ).fetchone()
                source_id = row[0] if row else uuid4().hex
                conn.execute(
                    """
                    INSERT INTO import_sources (
                        id, import_account_id, source_file_sha256, original_path,
                        archived_path, file_name, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(import_account_id, source_file_sha256)
                    DO UPDATE SET
                        original_path = excluded.original_path,
                        archived_path = excluded.archived_path,
                        file_name = excluded.file_name,
                        imported_at = excluded.imported_at
                    """,
                    (
                        source_id,
                        import_account_id,
                        source_file_sha256,
                        str(original_path) if original_path is not None else None,
                        str(archived_path) if archived_path is not None else None,
                        file_name,
                        now,
                    ),
                )

            for txn in txns:
                source_identity = str(txn.get("sourceIdentity") or "").strip()
                if not source_identity:
                    continue
                transaction_id = str(txn.get("transactionId") or "").strip() or None
                if transaction_id is not None:
                    projected = conn.execute(
                        "SELECT 1 FROM transactions WHERE id = ?",
                        (transaction_id,),
                    ).fetchone()
                    if projected is None:
                        transaction_id = None
                conn.execute(
                    """
                    INSERT INTO import_identities (
                        id, import_account_id, source_identity, source_payload_hash,
                        transaction_id, import_source_id, first_seen_at,
                        last_seen_at, current_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                    ON CONFLICT(import_account_id, source_identity)
                    DO UPDATE SET
                        source_payload_hash = excluded.source_payload_hash,
                        transaction_id = excluded.transaction_id,
                        import_source_id = excluded.import_source_id,
                        last_seen_at = excluded.last_seen_at,
                        current_status = 'active'
                    """,
                    (
                        uuid4().hex,
                        import_account_id,
                        source_identity,
                        txn.get("sourcePayloadHash"),
                        transaction_id,
                        source_id,
                        now,
                        now,
                    ),
                )
        return source_id

    def mark_undone(self, import_account_id: str, source_identities: list[str]) -> None:
        identities = [identity for identity in source_identities if identity]
        if not identities:
            return
        now = datetime.now(UTC).isoformat()
        with connect(self._db_path()) as conn:
            conn.executemany(
                """
                UPDATE import_identities
                SET current_status = 'undone', last_seen_at = ?
                WHERE import_account_id = ? AND source_identity = ?
                """,
                [(now, import_account_id, source_identity) for source_identity in identities],
            )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonicalize_payload_line(line: str, institution_account: str) -> str:
    match = ACCOUNT_LINE_RE.match(line)
    if match and match.group(2).strip() == institution_account:
        return f"{match.group(1)}{IMPORT_ACCOUNT_PLACEHOLDER}{match.group(3)}{match.group(4)}"

    match = ACCOUNT_ONLY_RE.match(line)
    if match and match.group(2).strip() == institution_account:
        return f"{match.group(1)}{IMPORT_ACCOUNT_PLACEHOLDER}"

    return line


def source_payload_hash_for_lines(
    lines: list[str],
    institution_account: str,
    base_currency: str | None = None,
) -> str:
    canonical_lines = [
        canonicalize_base_currency_posting(
            _canonicalize_payload_line(line.rstrip(), institution_account),
            base_currency or "",
        )
        for line in lines
        if not META_RE.match(line)
    ]
    normalized = "\n".join(canonical_lines).strip() + "\n"
    return _sha256_text(normalized)
