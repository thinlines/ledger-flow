from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException

from .archive_service import archive_manual_entry, rollback_archive
from .config_service import AppConfig
from .import_index import ImportIndex
from .journal_block_service import find_transaction_block, locate_header_at
from .reconciliation_context_service import (
    IMPORT_IDENTITY_KEY_RE,
    ReconciliationContext,
    ReconciliationContextRow,
    build_reconciliation_context,
)

ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")

MATCH_WINDOW_DAYS = 3


@dataclass(frozen=True)
class DuplicateCandidate:
    row: ReconciliationContextRow
    confidence: int
    reason: str
    action: Literal["remove_manual_duplicate", "use_imported_transaction", "merge_imported_duplicates"] | None
    action_label: str | None
    action_blocked_reason: str | None


def _normalize_payee(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _payee_similarity(left: str, right: str) -> float:
    left_norm = _normalize_payee(left)
    right_norm = _normalize_payee(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _candidate_reason(date_diff: int, payee_score: float) -> tuple[str, int]:
    if payee_score >= 0.92 and date_diff == 0:
        return "Same amount, same day, and nearly the same payee.", 300
    if payee_score >= 0.72:
        return f"Same amount and a similar payee within {date_diff} day{'s' if date_diff != 1 else ''}.", 220 - date_diff
    if date_diff <= 1:
        return f"Same amount and posted within {date_diff} day{'s' if date_diff != 1 else ''}.", 160 - date_diff
    return "", 0


def _action_for_pair(checked: ReconciliationContextRow, unchecked: ReconciliationContextRow) -> tuple[str | None, str | None, str | None]:
    if unchecked.line_number < 0:
        return None, None, "This transaction cannot be changed from this journal view."
    if checked.is_imported and unchecked.is_imported:
        if checked.journal_path != unchecked.journal_path:
            return None, None, "These imported transactions live in different journals, so they cannot be merged here."
        return "merge_imported_duplicates", "Merge imported duplicates", None
    if checked.is_imported and unchecked.is_manual:
        return "remove_manual_duplicate", "Remove manual duplicate", None if unchecked.can_delete else "This manual transaction cannot be removed safely."
    if checked.is_manual and unchecked.is_imported:
        return "use_imported_transaction", "Use imported transaction", None
    if checked.is_manual and unchecked.is_manual:
        return "remove_manual_duplicate", "Remove manual duplicate", None if unchecked.can_delete else "This manual transaction cannot be removed safely."
    return None, None, None


def build_duplicate_groups(
    context: ReconciliationContext,
    checked_selection_keys: set[str],
) -> list[dict]:
    checked_rows = [row for row in context.transactions if row.selection_key in checked_selection_keys]
    unchecked_rows = [row for row in context.transactions if row.selection_key not in checked_selection_keys]
    groups: list[dict] = []

    for checked in checked_rows:
        candidates: list[DuplicateCandidate] = []
        checked_date = date.fromisoformat(checked.date)
        for unchecked in unchecked_rows:
            if checked.selection_key == unchecked.selection_key:
                continue
            if abs(checked.signed_amount) != abs(unchecked.signed_amount):
                continue

            unchecked_date = date.fromisoformat(unchecked.date)
            date_diff = abs((checked_date - unchecked_date).days)
            if date_diff > MATCH_WINDOW_DAYS:
                continue

            payee_score = _payee_similarity(checked.payee, unchecked.payee)
            reason, confidence = _candidate_reason(date_diff, payee_score)
            if not reason:
                continue

            action, action_label, blocked_reason = _action_for_pair(checked, unchecked)
            candidates.append(
                DuplicateCandidate(
                    row=unchecked,
                    confidence=confidence,
                    reason=reason,
                    action=action,
                    action_label=action_label,
                    action_blocked_reason=blocked_reason,
                )
            )

        candidates.sort(key=lambda candidate: (-candidate.confidence, candidate.row.date, candidate.row.payee))
        if candidates:
            groups.append(
                {
                    "checked": checked,
                    "matches": candidates,
                }
            )

    return groups


def _read_block(row: ReconciliationContextRow) -> tuple[Path, list[str], int, int]:
    journal_path = Path(row.journal_path)
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    try:
        header_idx = locate_header_at(lines, row.line_number, row.header_line)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Transaction moved since this page loaded. Refresh and try again.") from exc
    block_start, block_end = find_transaction_block(lines, header_idx)
    return journal_path, lines, block_start, block_end


def _extract_metadata(block_lines: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in block_lines[1:]:
        match = META_RE.match(line)
        if match:
            metadata[match.group(1).strip().lower()] = match.group(2).strip()
    return metadata


def _find_other_posting(block_lines: list[str], ledger_account: str) -> tuple[int | None, str | None]:
    for idx, line in enumerate(block_lines[1:], start=1):
        if line.strip().startswith(";"):
            continue
        match = ACCOUNT_LINE_RE.match(line) or ACCOUNT_ONLY_RE.match(line)
        if not match:
            continue
        account = match.group(2).strip()
        if account != ledger_account:
            return idx, account
    return None, None


def _rewrite_posting_account(line: str, target_account: str) -> str:
    match = ACCOUNT_LINE_RE.match(line)
    if match:
        return f"{match.group(1)}{target_account}{match.group(3)}{match.group(4)}"
    match = ACCOUNT_ONLY_RE.match(line)
    if match:
        return f"{match.group(1)}{target_account}"
    raise HTTPException(status_code=422, detail="Could not rewrite the duplicate transaction.")


def _user_metadata_lines(block_lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in block_lines[1:]:
        stripped = line.strip()
        if not stripped.startswith(";"):
            continue
        if stripped == "; :manual:":
            continue
        match = META_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip().lower()
        if key.startswith("source_identity") or key.startswith("source_payload_hash"):
            continue
        if key in {
            "import_account_id",
            "institution_template",
            "source_file_sha256",
            "importer_version",
            "match-id",
            "reconciliation_event_id",
            "statement_period",
        }:
            continue
        out.append(line)
    return out


def _replace_user_metadata(block_lines: list[str], user_metadata_lines: list[str]) -> list[str]:
    kept = [block_lines[0]]
    inserted = False
    for line in block_lines[1:]:
        match = META_RE.match(line)
        if match:
            key = match.group(1).strip().lower()
            if key == "notes":
                continue
            if key.startswith("source_identity") or key.startswith("source_payload_hash"):
                kept.append(line)
                continue
            if key in {"source_file_sha256", "importer_version", "import_account_id", "institution_template", "match-id"}:
                kept.append(line)
                continue
            if line.strip() == "; :manual:":
                kept.append(line)
                continue
            continue
        if not inserted and user_metadata_lines:
            kept.extend(user_metadata_lines)
            inserted = True
        kept.append(line)
    if not inserted and user_metadata_lines:
        kept.extend(user_metadata_lines)
    return kept


def _upsert_match_tags(block_lines: list[str], match_id: str) -> list[str]:
    out = [block_lines[0]]
    has_manual_tag = False
    has_match_id = False
    for line in block_lines[1:]:
        if line.strip() == "; :manual:":
            has_manual_tag = True
        if line.strip() == f"; match-id: {match_id}":
            has_match_id = True
        out.append(line)
    insert_at = 1
    if not has_match_id:
        out.insert(insert_at, f"    ; match-id: {match_id}")
    if not has_manual_tag:
        out.insert(insert_at, "    ; :manual:")
    return out


def _import_identity_variants(metadata: dict[str, str]) -> list[dict[str, str | None]]:
    variants: list[tuple[int, dict[str, str | None]]] = []

    def add_variant(suffix: int | None) -> None:
        suffix_part = "" if suffix is None else f"_{suffix}"
        identity = str(metadata.get(f"source_identity{suffix_part}") or "").strip()
        if not identity:
            return
        variants.append(
            (
                1 if suffix is None else suffix,
                {
                    "sourceIdentity": identity,
                    "sourcePayloadHash": str(metadata.get(f"source_payload_hash{suffix_part}") or "").strip() or None,
                    "sourceFileSha256": str(metadata.get(f"source_file_sha256{suffix_part}") or "").strip() or None,
                    "importerVersion": str(metadata.get(f"importer_version{suffix_part}") or "").strip() or None,
                },
            )
        )

    add_variant(None)
    suffixes: list[int] = []
    for key in metadata:
        match = re.match(r"^source_identity_(\d+)$", key)
        if match:
            suffixes.append(int(match.group(1)))
    for suffix in sorted(set(suffixes)):
        add_variant(suffix)

    return [variant for _, variant in sorted(variants, key=lambda item: item[0])]


def _upsert_import_identity_metadata(
    survivor_lines: list[str],
    imported_metadata: dict[str, str],
) -> list[str]:
    variants = _import_identity_variants(imported_metadata)
    if not variants:
        raise HTTPException(status_code=422, detail="Imported duplicate is missing import identity metadata.")

    existing = _extract_metadata(survivor_lines)
    existing_identities = {value for key, value in existing.items() if IMPORT_IDENTITY_KEY_RE.match(key)}
    metadata_lines: list[str] = []
    next_suffix = 2
    while f"source_identity_{next_suffix}" in existing:
        next_suffix += 1

    for variant in variants:
        identity = str(variant["sourceIdentity"] or "").strip()
        if not identity or identity in existing_identities:
            continue
        metadata_lines.append(f"    ; source_identity_{next_suffix}: {identity}")
        payload = str(variant["sourcePayloadHash"] or "").strip()
        if payload:
            metadata_lines.append(f"    ; source_payload_hash_{next_suffix}: {payload}")
        file_sha = str(variant["sourceFileSha256"] or "").strip()
        if file_sha:
            metadata_lines.append(f"    ; source_file_sha256_{next_suffix}: {file_sha}")
        importer_version = str(variant["importerVersion"] or "").strip()
        if importer_version:
            metadata_lines.append(f"    ; importer_version_{next_suffix}: {importer_version}")
        existing_identities.add(identity)
        next_suffix += 1

    if not metadata_lines:
        return survivor_lines
    return [survivor_lines[0], *metadata_lines, *survivor_lines[1:]]


def _write_journal(path: Path, lines: list[str], trailing_newline: bool = True) -> None:
    text = "\n".join(lines)
    if trailing_newline:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def resolve_duplicate_candidate(
    *,
    config: AppConfig,
    tracked_account_id: str,
    checked_row: ReconciliationContextRow,
    unchecked_row: ReconciliationContextRow,
    action: str,
) -> dict:
    tracked_account_cfg = config.tracked_accounts.get(tracked_account_id)
    if tracked_account_cfg is None:
        raise HTTPException(status_code=404, detail="Tracked account not found.")
    ledger_account = str(tracked_account_cfg.get("ledger_account") or "").strip()
    if not ledger_account:
        raise HTTPException(status_code=400, detail="Tracked account is missing a ledger account.")

    if action == "remove_manual_duplicate":
        target = unchecked_row
        journal_path, lines, block_start, block_end = _read_block(target)
        remove_start = block_start
        if remove_start > 0 and lines[remove_start - 1].strip() == "":
            remove_start -= 1
        del lines[remove_start:block_end]
        _write_journal(journal_path, lines)
        return {
            "removedSelectionKeys": [target.selection_key],
            "addedCheckedSelectionKeys": [],
        }

    if action == "use_imported_transaction":
        manual_row = checked_row
        imported_row = unchecked_row
        manual_journal, manual_lines, manual_start, manual_end = _read_block(manual_row)
        imported_journal, imported_lines, imported_start, imported_end = _read_block(imported_row)
        if manual_journal == imported_journal:
            shared_lines = manual_journal.read_text(encoding="utf-8").splitlines()
            manual_header_idx = locate_header_at(shared_lines, manual_row.line_number, manual_row.header_line)
            imported_header_idx = locate_header_at(shared_lines, imported_row.line_number, imported_row.header_line)
            manual_start, manual_end = find_transaction_block(shared_lines, manual_header_idx)
            imported_start, imported_end = find_transaction_block(shared_lines, imported_header_idx)
            manual_block = shared_lines[manual_start:manual_end]
            imported_block = shared_lines[imported_start:imported_end]
        else:
            manual_block = manual_lines[manual_start:manual_end]
            imported_block = imported_lines[imported_start:imported_end]

        _, destination_account = _find_other_posting(manual_block, ledger_account)
        if not destination_account:
            raise HTTPException(status_code=422, detail="Manual duplicate is missing a category to carry over.")
        imported_posting_idx, imported_other_account = _find_other_posting(imported_block, ledger_account)
        if imported_posting_idx is None or imported_other_account is None:
            raise HTTPException(status_code=422, detail="Imported duplicate does not have a usable category posting.")

        updated_imported = list(imported_block)
        if imported_other_account != destination_account:
            updated_imported[imported_posting_idx] = _rewrite_posting_account(
                updated_imported[imported_posting_idx],
                destination_account,
            )
        updated_imported = _replace_user_metadata(updated_imported, _user_metadata_lines(manual_block))
        match_id = str(uuid4())
        updated_imported = _upsert_match_tags(updated_imported, match_id)

        archive_path = config.journal_dir / "archived-manual.journal"
        archive_size_before = archive_path.stat().st_size if archive_path.exists() else None
        try:
            archive_manual_entry(archive_path, match_id, manual_block)
            if manual_journal == imported_journal:
                shared_lines[imported_start:imported_end] = updated_imported
                if imported_start < manual_start:
                    manual_start += len(updated_imported) - len(imported_block)
                    manual_end += len(updated_imported) - len(imported_block)
                manual_remove_end = manual_end
                while manual_remove_end < len(shared_lines) and not shared_lines[manual_remove_end].strip():
                    manual_remove_end += 1
                del shared_lines[manual_start:manual_remove_end]
                _write_journal(manual_journal, shared_lines)
            else:
                imported_lines[imported_start:imported_end] = updated_imported
                manual_remove_end = manual_end
                while manual_remove_end < len(manual_lines) and not manual_lines[manual_remove_end].strip():
                    manual_remove_end += 1
                del manual_lines[manual_start:manual_remove_end]
                _write_journal(imported_journal, imported_lines)
                _write_journal(manual_journal, manual_lines)
        except Exception:
            rollback_archive(archive_path, archive_size_before)
            raise

        return {
            "removedSelectionKeys": [manual_row.selection_key],
            "addedCheckedSelectionKeys": [imported_row.selection_key],
        }

    if action == "merge_imported_duplicates":
        survivor_row = checked_row
        merged_row = unchecked_row
        journal_path, lines, survivor_start, survivor_end = _read_block(survivor_row)
        merge_journal_path, merge_lines, merge_start, merge_end = _read_block(merged_row)
        if journal_path != merge_journal_path:
            raise HTTPException(status_code=422, detail="Imported duplicates must live in the same journal file to merge.")

        survivor_block = lines[survivor_start:survivor_end]
        merged_block = merge_lines[merge_start:merge_end]
        merged_metadata = _extract_metadata(merged_block)
        updated_survivor = _upsert_import_identity_metadata(survivor_block, merged_metadata)

        lines[survivor_start:survivor_end] = updated_survivor
        merge_end_adjusted = merge_end + (len(updated_survivor) - len(survivor_block)) if merge_start > survivor_start else merge_end
        remove_start = merge_start
        if remove_start > 0 and lines[remove_start - 1].strip() == "":
            remove_start -= 1
        del lines[remove_start:merge_end_adjusted]
        _write_journal(journal_path, lines)

        import_account_id = str(merged_row.import_account_id or survivor_row.import_account_id or "").strip()
        if import_account_id:
            year = Path(journal_path).stem
            txns = _import_identity_variants(_extract_metadata(updated_survivor))
            if txns:
                ImportIndex(config.root_dir / ".workflow" / "state.db").upsert_transactions(
                    import_account_id,
                    year,
                    journal_path,
                    str(txns[0].get("sourceFileSha256") or ""),
                    txns,
                )

        return {
            "removedSelectionKeys": [merged_row.selection_key],
            "addedCheckedSelectionKeys": [],
        }

    raise HTTPException(status_code=422, detail="Unsupported duplicate resolution action.")


def build_duplicate_review_payload(
    *,
    config: AppConfig,
    tracked_account_id: str,
    period_start: date,
    period_end: date,
    checked_selection_keys: set[str],
) -> tuple[ReconciliationContext, list[dict]]:
    tracked_account_cfg = config.tracked_accounts.get(tracked_account_id)
    if tracked_account_cfg is None:
        raise HTTPException(status_code=404, detail=f"Tracked account not found: {tracked_account_id}")
    context = build_reconciliation_context(
        config=config,
        tracked_account_cfg=tracked_account_cfg,
        period_start=period_start,
        period_end=period_end,
    )
    return context, build_duplicate_groups(context, checked_selection_keys)
