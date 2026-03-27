from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re


TRANSFER_ROOT_ACCOUNT = "Assets:Transfers"
PAIR_SEPARATOR = "__"
TRANSFER_TYPE_DIRECT = "direct"
TRANSFER_TYPE_IMPORT_MATCH = "import_match"
TRANSFER_MATCH_STATE_NONE = "none"
TRANSFER_MATCH_STATE_PENDING = "pending"
TRANSFER_MATCH_STATE_MATCHED = "matched"
TRANSFER_STATE_SETTLED_GROUPED = "settled_grouped"
MANUAL_TRANSFER_RESOLUTION_METADATA_KEY = "transfer_manual_resolution"
MANUAL_TRANSFER_RESOLUTION_METADATA_VALUE = "missing_import_counterpart"
MANUAL_TRANSFER_RESOLUTION_TOKEN_KIND = "pending_import_transfer_resolution"
MANUAL_TRANSFER_RESOLUTION_TOKEN_VERSION = 1
MAX_TRANSFER_MATCH_DAYS = 7
VALID_TRANSFER_TYPES = {TRANSFER_TYPE_DIRECT, TRANSFER_TYPE_IMPORT_MATCH}
VALID_TRANSFER_MATCH_STATES = {
    TRANSFER_MATCH_STATE_NONE,
    TRANSFER_MATCH_STATE_PENDING,
    TRANSFER_MATCH_STATE_MATCHED,
}
ACTIVE_TRANSFER_MATCH_STATES = {
    TRANSFER_MATCH_STATE_PENDING,
    TRANSFER_MATCH_STATE_MATCHED,
}
ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")


@dataclass(frozen=True)
class ParsedTransferMetadata:
    transfer_id: str | None
    peer_account_id: str | None
    transfer_type: str | None
    transfer_match_state: str | None
    transfer_state_for_ui: str | None
    raw_transfer_type: str | None
    raw_transfer_match_state: str | None
    raw_transfer_state: str | None

    @property
    def has_linkage(self) -> bool:
        return bool(self.transfer_id or self.peer_account_id)

    @property
    def has_any_transfer_metadata(self) -> bool:
        return bool(
            self.transfer_id
            or self.peer_account_id
            or self.raw_transfer_type
            or self.raw_transfer_match_state
            or self.raw_transfer_state
        )

    @property
    def is_pending(self) -> bool:
        return self.transfer_state_for_ui == TRANSFER_MATCH_STATE_PENDING

    @property
    def is_import_match(self) -> bool:
        return self.transfer_type == TRANSFER_TYPE_IMPORT_MATCH


def is_transfer_account(account: str) -> bool:
    cleaned = account.strip()
    return cleaned == TRANSFER_ROOT_ACCOUNT or cleaned.startswith(f"{TRANSFER_ROOT_ACCOUNT}:")


def transfer_pair_account(source_tracked_account_id: str, target_tracked_account_id: str) -> str:
    left, right = sorted([source_tracked_account_id.strip(), target_tracked_account_id.strip()])
    return f"{TRANSFER_ROOT_ACCOUNT}:{left}{PAIR_SEPARATOR}{right}"


def build_manual_transfer_resolution_token(
    *,
    import_account_id: str,
    source_identity: str,
    transfer_id: str,
    peer_account_id: str,
) -> str:
    payload = {
        "kind": MANUAL_TRANSFER_RESOLUTION_TOKEN_KIND,
        "v": MANUAL_TRANSFER_RESOLUTION_TOKEN_VERSION,
        "importAccountId": import_account_id.strip(),
        "sourceIdentity": source_identity.strip(),
        "transferId": transfer_id.strip(),
        "peerAccountId": peer_account_id.strip(),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_manual_transfer_resolution_token(token: str) -> dict[str, str]:
    trimmed = token.strip()
    if not trimmed:
        raise ValueError("Resolution token is required.")

    padding = "=" * (-len(trimmed) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(trimmed + padding).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Resolution token is invalid.") from exc

    if payload.get("kind") != MANUAL_TRANSFER_RESOLUTION_TOKEN_KIND:
        raise ValueError("Resolution token is invalid.")
    if payload.get("v") != MANUAL_TRANSFER_RESOLUTION_TOKEN_VERSION:
        raise ValueError("Resolution token is no longer supported.")

    import_account_id = str(payload.get("importAccountId") or "").strip()
    source_identity = str(payload.get("sourceIdentity") or "").strip()
    transfer_id = str(payload.get("transferId") or "").strip()
    peer_account_id = str(payload.get("peerAccountId") or "").strip()
    if not import_account_id or not source_identity or not transfer_id or not peer_account_id:
        raise ValueError("Resolution token is invalid.")

    return {
        "importAccountId": import_account_id,
        "sourceIdentity": source_identity,
        "transferId": transfer_id,
        "peerAccountId": peer_account_id,
    }


def _metadata_value(metadata: Mapping[str, object], key: str) -> str | None:
    return str(metadata.get(key) or "").strip() or None


def _peer_requires_import_match(
    tracked_accounts: Mapping[str, dict] | None,
    peer_account_id: str | None,
) -> bool | None:
    if tracked_accounts is None or peer_account_id is None:
        return None
    peer_account = tracked_accounts.get(peer_account_id, {})
    import_account_id = peer_account.get("import_account_id")
    return bool(str(import_account_id or "").strip())


def parse_transfer_metadata(
    metadata: Mapping[str, object],
    tracked_accounts: Mapping[str, dict] | None = None,
) -> ParsedTransferMetadata:
    transfer_id = _metadata_value(metadata, "transfer_id")
    peer_account_id = _metadata_value(metadata, "transfer_peer_account_id")
    raw_transfer_type = _metadata_value(metadata, "transfer_type")
    raw_transfer_match_state = _metadata_value(metadata, "transfer_match_state")
    raw_transfer_state = _metadata_value(metadata, "transfer_state")

    explicit_transfer_type = raw_transfer_type if raw_transfer_type in VALID_TRANSFER_TYPES else None
    explicit_match_state = raw_transfer_match_state if raw_transfer_match_state in VALID_TRANSFER_MATCH_STATES else None
    legacy_match_state = raw_transfer_state if raw_transfer_state in ACTIVE_TRANSFER_MATCH_STATES else None
    has_linkage = bool(transfer_id or peer_account_id)
    peer_requires_import_match = _peer_requires_import_match(tracked_accounts, peer_account_id)

    transfer_type: str | None = None
    transfer_match_state: str | None = None

    if (
        explicit_transfer_type == TRANSFER_TYPE_IMPORT_MATCH
        and explicit_match_state in ACTIVE_TRANSFER_MATCH_STATES
        and has_linkage
    ):
        transfer_type = TRANSFER_TYPE_IMPORT_MATCH
        transfer_match_state = explicit_match_state
    elif (
        explicit_transfer_type is None
        and explicit_match_state in ACTIVE_TRANSFER_MATCH_STATES
        and has_linkage
    ):
        transfer_type = TRANSFER_TYPE_IMPORT_MATCH
        transfer_match_state = explicit_match_state
    elif legacy_match_state is not None and has_linkage and peer_requires_import_match is True:
        transfer_type = TRANSFER_TYPE_IMPORT_MATCH
        transfer_match_state = legacy_match_state
    elif has_linkage or explicit_transfer_type == TRANSFER_TYPE_DIRECT:
        transfer_type = TRANSFER_TYPE_DIRECT
        transfer_match_state = TRANSFER_MATCH_STATE_NONE

    if (
        transfer_type == TRANSFER_TYPE_IMPORT_MATCH
        and transfer_match_state in ACTIVE_TRANSFER_MATCH_STATES
        and peer_requires_import_match is False
    ):
        transfer_type = TRANSFER_TYPE_DIRECT if has_linkage else None
        transfer_match_state = TRANSFER_MATCH_STATE_NONE if transfer_type is not None else None

    transfer_state_for_ui = (
        transfer_match_state
        if transfer_type == TRANSFER_TYPE_IMPORT_MATCH and transfer_match_state in ACTIVE_TRANSFER_MATCH_STATES
        else None
    )

    return ParsedTransferMetadata(
        transfer_id=transfer_id,
        peer_account_id=peer_account_id,
        transfer_type=transfer_type,
        transfer_match_state=transfer_match_state,
        transfer_state_for_ui=transfer_state_for_ui,
        raw_transfer_type=raw_transfer_type,
        raw_transfer_match_state=raw_transfer_match_state,
        raw_transfer_state=raw_transfer_state,
    )


def clear_transfer_metadata_updates() -> dict[str, str | None]:
    return {
        "transfer_id": None,
        "transfer_peer_account_id": None,
        "transfer_type": None,
        "transfer_match_state": None,
        "transfer_state": None,
    }


def build_transfer_metadata_updates(
    *,
    transfer_id: str | None,
    peer_account_id: str | None,
    transfer_type: str,
    transfer_match_state: str | None,
) -> dict[str, str | None]:
    transfer_id_clean = (transfer_id or "").strip() or None
    peer_account_id_clean = (peer_account_id or "").strip() or None
    transfer_type_clean = transfer_type.strip()
    transfer_match_state_clean = (transfer_match_state or "").strip() or None

    if transfer_type_clean not in VALID_TRANSFER_TYPES:
        raise ValueError(f"Unsupported transfer type: {transfer_type_clean}")
    if transfer_id_clean is None or peer_account_id_clean is None:
        raise ValueError("Transfer metadata requires both transfer_id and transfer_peer_account_id.")

    if transfer_type_clean == TRANSFER_TYPE_DIRECT:
        transfer_match_state_clean = TRANSFER_MATCH_STATE_NONE
    elif transfer_match_state_clean not in ACTIVE_TRANSFER_MATCH_STATES:
        raise ValueError(
            "Import-match transfers require transfer_match_state to be 'pending' or 'matched'."
        )

    return {
        "transfer_id": transfer_id_clean,
        "transfer_peer_account_id": peer_account_id_clean,
        "transfer_type": transfer_type_clean,
        "transfer_match_state": transfer_match_state_clean,
        "transfer_state": None,
    }


def build_direct_transfer_metadata_updates(
    *,
    transfer_id: str | None,
    peer_account_id: str | None,
) -> dict[str, str | None]:
    return build_transfer_metadata_updates(
        transfer_id=transfer_id,
        peer_account_id=peer_account_id,
        transfer_type=TRANSFER_TYPE_DIRECT,
        transfer_match_state=TRANSFER_MATCH_STATE_NONE,
    )


def build_import_match_transfer_metadata_updates(
    *,
    transfer_id: str | None,
    peer_account_id: str | None,
    transfer_match_state: str,
) -> dict[str, str | None]:
    return build_transfer_metadata_updates(
        transfer_id=transfer_id,
        peer_account_id=peer_account_id,
        transfer_type=TRANSFER_TYPE_IMPORT_MATCH,
        transfer_match_state=transfer_match_state,
    )


def parse_amount(raw: str) -> Decimal | None:
    compact = re.sub(r"\s+", "", raw)
    if not compact:
        return None

    digits = "".join(ch for ch in compact if ch.isdigit() or ch in {".", ","})
    if not digits:
        return None

    sign = -1 if "-" in compact else 1
    try:
        return Decimal(digits.replace(",", "")) * sign
    except InvalidOperation:
        return None


def infer_blank_posting_amounts(postings: list[dict]) -> list[dict]:
    normalized = [dict(posting) for posting in postings]
    blank_indexes = [index for index, posting in enumerate(normalized) if posting.get("amountNumber") is None]
    if len(blank_indexes) != 1:
        return normalized

    known_total = sum(
        (posting.get("amountNumber") or Decimal("0"))
        for posting in normalized
        if posting.get("amountNumber") is not None
    )
    idx = blank_indexes[0]
    normalized[idx]["amountNumber"] = -known_total
    return normalized


def parse_metadata_lines(lines: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in lines:
        match = META_RE.match(line)
        if match:
            metadata[match.group(1).strip().lower()] = match.group(2).strip()
    return metadata


def upsert_transaction_metadata(txn_lines: list[str], updates: dict[str, str | None]) -> list[str]:
    if not txn_lines:
        return []

    updated = list(txn_lines)
    existing_indexes: dict[str, int] = {}
    for index, line in enumerate(updated[1:], start=1):
        match = META_RE.match(line)
        if not match:
            continue
        existing_indexes[match.group(1).strip().lower()] = index

    # Remove keys first so inserts land in the right place.
    removals = sorted(
        (existing_indexes[key] for key, value in updates.items() if value is None and key in existing_indexes),
        reverse=True,
    )
    for index in removals:
        updated.pop(index)

    existing_indexes = {}
    insert_at = 1
    for index, line in enumerate(updated[1:], start=1):
        match = META_RE.match(line)
        if match:
            existing_indexes[match.group(1).strip().lower()] = index
            insert_at = index + 1
            continue
        break

    inserts: list[str] = []
    for key, value in updates.items():
        if value is None:
            continue
        line = f"    ; {key}: {value}"
        if key in existing_indexes:
            updated[existing_indexes[key]] = line
        else:
            inserts.append(line)

    if inserts:
        updated[insert_at:insert_at] = inserts

    return updated


def rewrite_posting_account(line: str, target_account: str) -> tuple[str, bool]:
    match = ACCOUNT_LINE_RE.match(line)
    if match:
        return (f"{match.group(1)}{target_account}{match.group(3)}{match.group(4)}", True)

    match = ACCOUNT_ONLY_RE.match(line)
    if match:
        return (f"{match.group(1)}{target_account}", True)

    return line, False


def ensure_transfer_account(accounts_dat: Path, source_tracked_account_id: str, target_tracked_account_id: str) -> str:
    transfer_account = transfer_pair_account(source_tracked_account_id, target_tracked_account_id)
    lines = accounts_dat.read_text(encoding="utf-8").splitlines() if accounts_dat.exists() else []
    known_accounts = {
        line[len("account "):].strip()
        for line in lines
        if line.startswith("account ")
    }
    if transfer_account in known_accounts:
        return transfer_account

    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"account {transfer_account}")
    lines.append("    ; type: Asset")
    lines.append("    ; description: Internal transfer clearing account")
    accounts_dat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return transfer_account
