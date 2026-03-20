from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .config_service import infer_account_kind
from .rules_service import extract_set_account, find_matching_rule
from .transfer_service import (
    ensure_transfer_account,
    infer_blank_posting_amounts,
    is_transfer_account,
    parse_amount,
    rewrite_posting_account,
    upsert_transaction_metadata,
)

ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
HEADER_RE = re.compile(r"^(\d{4}[-/]\d{2}[-/]\d{2})(?:\s+[*!])?(?:\s+\([^)]+\))?\s*(.*)$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")
MAX_TRANSFER_MATCH_DAYS = 7


def list_known_accounts(accounts_dat: Path) -> list[str]:
    return sorted(_load_known_accounts(accounts_dat))


def list_category_accounts(accounts_dat: Path) -> list[str]:
    return sorted(
        account
        for account in _load_known_accounts(accounts_dat)
        if infer_account_kind(account) in {"expense", "income"} and not is_transfer_account(account)
    )


def _load_known_accounts(accounts_dat: Path) -> set[str]:
    known = set()
    if not accounts_dat.exists():
        return known
    for line in accounts_dat.read_text(encoding="utf-8").splitlines():
        if line.startswith("account "):
            known.add(line[len("account "):].strip())
    return known


def _load_payee_rules(accounts_dat: Path) -> dict[str, str]:
    current_account = None
    mapping = {}
    if not accounts_dat.exists():
        return mapping
    for raw in accounts_dat.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("account "):
            current_account = line[len("account "):].strip()
            continue
        if current_account and line.strip().startswith("payee "):
            payee = line.strip()[len("payee "):].strip()
            mapping[payee.lower()] = current_account
    return mapping


def _iter_transaction_ranges(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines) if TXN_START_RE.match(line)]
    ranges: list[tuple[int, int]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        ranges.append((start, end))
    return ranges


def _parse_postings(lines: list[str], start: int, end: int) -> list[dict]:
    postings = []
    for i in range(start + 1, end):
        line = lines[i]
        m = ACCOUNT_LINE_RE.match(line)
        if m:
            postings.append(
                {
                    "lineNo": i + 1,
                    "indent": m.group(1),
                    "account": m.group(2).strip(),
                    "sep": m.group(3),
                    "amount": m.group(4).strip(),
                    "line": line,
                }
            )
            continue

        if line.lstrip().startswith(";"):
            continue

        m = ACCOUNT_ONLY_RE.match(line)
        if not m:
            continue

        postings.append(
            {
                "lineNo": i + 1,
                "indent": m.group(1),
                "account": m.group(2).strip(),
                "sep": "",
                "amount": "",
                "line": line,
            }
        )
    return postings


def _parse_metadata(lines: list[str], start: int, end: int) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for i in range(start + 1, end):
        mm = META_RE.match(lines[i])
        if mm:
            metadata[mm.group(1).strip().lower()] = mm.group(2).strip()
    return metadata


def _group_key(payee: str, import_account_id: str | None) -> str:
    key = payee.lower()
    if import_account_id:
        return f"{key}::{import_account_id.lower()}"
    return key


def _parse_posted_on(value: str) -> date | None:
    cleaned = value.replace("/", "-").strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def _tracked_account_context(
    metadata: dict[str, str],
    postings: list[dict],
    import_accounts: dict[str, dict],
    tracked_accounts: dict[str, dict],
    counterparty: str,
) -> dict:
    import_account_id = metadata.get("import_account_id") or None
    import_account_cfg = import_accounts.get(import_account_id or "", {}) if import_account_id else {}
    source_tracked_account_id = str(import_account_cfg.get("tracked_account_id", "")).strip() or None
    if source_tracked_account_id is None and import_account_id and import_account_id in tracked_accounts:
        source_tracked_account_id = import_account_id

    source_tracked_cfg = tracked_accounts.get(source_tracked_account_id or "", {}) if source_tracked_account_id else {}
    source_ledger_account = str(
        source_tracked_cfg.get("ledger_account") or import_account_cfg.get("ledger_account") or ""
    ).strip()
    if not source_ledger_account:
        source_ledger_account = counterparty.strip()

    if not source_tracked_account_id and counterparty:
        for tracked_account_id, tracked_account_cfg in tracked_accounts.items():
            if str(tracked_account_cfg.get("ledger_account", "")).strip() == counterparty:
                source_tracked_account_id = tracked_account_id
                source_tracked_cfg = tracked_account_cfg
                source_ledger_account = counterparty
                break

    source_account_label = (
        str(source_tracked_cfg.get("display_name") or import_account_cfg.get("display_name") or "").strip()
        or None
    )
    source_posting = next(
        (posting for posting in postings if posting["account"] == source_ledger_account),
        None,
    )

    return {
        "importAccountId": import_account_id,
        "importAccountDisplayName": (
            str(import_account_cfg.get("display_name", import_account_id)).strip() if import_account_id else None
        ),
        "importLedgerAccount": str(import_account_cfg.get("ledger_account", "")).strip() or None,
        "sourceTrackedAccountId": source_tracked_account_id,
        "sourceTrackedAccountKind": infer_account_kind(source_ledger_account) if source_ledger_account else None,
        "sourceLedgerAccount": source_ledger_account or None,
        "sourceAccountLabel": source_account_label or counterparty or None,
        "sourceAmountNumber": source_posting.get("amountNumber") if source_posting else None,
    }


def _transaction_base_id(journal_path: Path, start_line: int, metadata: dict[str, str]) -> str:
    source_identity = str(metadata.get("source_identity", "")).strip()
    if source_identity:
        return source_identity
    return f"{journal_path.name}:tx:{start_line}"


def _build_transaction_records(
    journal_path: Path,
    import_accounts: dict[str, dict],
    tracked_accounts: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    grouped: dict[str, dict] = defaultdict(lambda: {"txns": [], "_matchSignatures": []})
    transaction_records: list[dict] = []

    for start, end in _iter_transaction_ranges(lines):
        header_line = lines[start]
        match = HEADER_RE.match(header_line)
        if match:
            current_date = match.group(1)
            current_payee = match.group(2).strip() or "(no payee)"
        else:
            current_date = ""
            current_payee = "(no payee)"

        metadata = _parse_metadata(lines, start, end)
        raw_postings = _parse_postings(lines, start, end)
        postings = infer_blank_posting_amounts(
            [
                {
                    **posting,
                    "amountNumber": parse_amount(posting["amount"]),
                }
                for posting in raw_postings
            ]
        )
        unknown_postings = [posting for posting in postings if "Unknown" in posting["account"]]
        counterparty = next((posting["account"] for posting in postings if "Unknown" not in posting["account"]), "")
        context = _tracked_account_context(metadata, postings, import_accounts, tracked_accounts, counterparty)
        base_txn_id = _transaction_base_id(journal_path, start + 1, metadata)
        record = {
            "txnId": base_txn_id,
            "payeeDisplay": current_payee,
            "date": current_date,
            "postedOn": _parse_posted_on(current_date),
            "transactionStartLine": start + 1,
            "transactionEndLine": end,
            "unknownPostingCount": len(unknown_postings),
            "postings": postings,
            "metadata": metadata,
            "transferId": metadata.get("transfer_id"),
            "transferState": metadata.get("transfer_state"),
            "transferPeerAccountId": metadata.get("transfer_peer_account_id"),
            **context,
        }

        transaction_records.append(record)
        if not unknown_postings:
            continue

        key = _group_key(current_payee, context["importAccountId"])
        group = grouped[key]
        group["groupKey"] = key
        group["payeeDisplay"] = current_payee
        group["importAccountId"] = context["importAccountId"]
        group["importAccountDisplayName"] = context["importAccountDisplayName"]
        group["importLedgerAccount"] = context["importLedgerAccount"]
        group["sourceAccountLabel"] = context["sourceAccountLabel"]
        group["sourceLedgerAccount"] = context["sourceLedgerAccount"]
        group["sourceTrackedAccountId"] = context["sourceTrackedAccountId"]
        group["sourceTrackedAccountKind"] = context["sourceTrackedAccountKind"]

        for posting in unknown_postings:
            row = {
                "txnId": f"{base_txn_id}:{posting['lineNo']}",
                "transactionId": base_txn_id,
                "date": current_date,
                "lineNo": posting["lineNo"],
                "transactionStartLine": start + 1,
                "transactionEndLine": end,
                "currentAccount": posting["account"],
                "amount": posting["amount"],
                "counterpartyAccount": counterparty,
                "line": posting["line"],
                "sourceTrackedAccountId": context["sourceTrackedAccountId"],
                "sourceTrackedAccountKind": context["sourceTrackedAccountKind"],
                "transferSuggestion": None,
            }
            group["txns"].append(row)
            record.setdefault("unknownRows", []).append(row)

    return transaction_records, list(grouped.values())


def _transfer_match(current: dict, candidate: dict) -> bool:
    current_amount = current.get("sourceAmountNumber")
    candidate_amount = candidate.get("sourceAmountNumber")
    current_date = current.get("postedOn")
    candidate_date = candidate.get("postedOn")
    if current_amount is None or candidate_amount is None:
        return False
    if current_date is None or candidate_date is None:
        return False
    if current.get("sourceTrackedAccountId") == candidate.get("sourceTrackedAccountId"):
        return False
    if current_amount + candidate_amount != Decimal("0"):
        return False
    return abs((current_date - candidate_date).days) <= MAX_TRANSFER_MATCH_DAYS


def _build_transfer_suggestion(current: dict, candidate: dict) -> dict:
    suggestion = {
        "candidateTxnId": candidate.get("unknownRows", [{}])[0].get("txnId") or candidate["txnId"],
        "candidateState": candidate.get("transferState") or "unknown",
        "candidateTransferId": candidate.get("transferId"),
        "targetTrackedAccountId": candidate["sourceTrackedAccountId"],
        "targetTrackedAccountName": candidate["sourceAccountLabel"],
        "targetTrackedAccountKind": candidate["sourceTrackedAccountKind"],
        "candidateTransactionStartLine": candidate["transactionStartLine"],
        "candidateTransactionEndLine": candidate["transactionEndLine"],
        "candidateGroupKey": _group_key(candidate["payeeDisplay"], candidate.get("importAccountId")),
    }
    if candidate.get("unknownRows"):
        suggestion["candidateUnknownLineNo"] = candidate["unknownRows"][0]["lineNo"]
    return suggestion


def _populate_transfer_suggestions(transaction_records: list[dict]) -> None:
    eligible_unknowns = [
        record
        for record in transaction_records
        if record.get("importAccountId")
        and record.get("sourceTrackedAccountId")
        and record.get("unknownPostingCount") == 1
        and not record.get("transferState")
    ]
    pending_transfers = [
        record
        for record in transaction_records
        if record.get("transferState") == "pending"
        and record.get("sourceTrackedAccountId")
        and record.get("transferPeerAccountId")
    ]

    for current in eligible_unknowns:
        matches: list[dict] = []
        for candidate in eligible_unknowns:
            if candidate["txnId"] == current["txnId"]:
                continue
            if _transfer_match(current, candidate):
                matches.append(_build_transfer_suggestion(current, candidate))

        for candidate in pending_transfers:
            if candidate.get("transferPeerAccountId") != current.get("sourceTrackedAccountId"):
                continue
            if _transfer_match(current, candidate):
                matches.append(_build_transfer_suggestion(current, candidate))

        if len(matches) == 1:
            current["unknownRows"][0]["transferSuggestion"] = matches[0]


def scan_unknowns(
    journal_path: Path,
    rules: list[dict],
    import_accounts: dict[str, dict] | None = None,
    tracked_accounts: dict[str, dict] | None = None,
) -> dict:
    transaction_records, groups = _build_transaction_records(
        journal_path,
        import_accounts or {},
        tracked_accounts or {},
    )
    _populate_transfer_suggestions(transaction_records)

    for group in groups:
        for txn in group["txns"]:
            matched = find_matching_rule(
                {"payee": group["payeeDisplay"], "date": txn["date"].replace("/", "-")},
                rules,
            )
            group["_matchSignatures"].append(
                (
                    matched["id"] if matched else None,
                    extract_set_account(matched) if matched else None,
                    matched["conditions"][0]["value"] if matched else None,
                )
            )

    for group in groups:
        signatures = {tuple(signature) for signature in group.pop("_matchSignatures", [])}
        if len(signatures) == 1:
            matched_rule_id, suggested_account, matched_pattern = next(iter(signatures))
            group["suggestedAccount"] = suggested_account
            group["matchedRuleId"] = matched_rule_id
            group["matchedRulePattern"] = matched_pattern
        else:
            group["suggestedAccount"] = None
            group["matchedRuleId"] = None
            group["matchedRulePattern"] = None

    return {"groups": groups}


def _stage_category_selections(selections: dict[str, dict]) -> dict[str, str]:
    return {
        group_key: str(selection.get("categoryAccount", "")).strip()
        for group_key, selection in selections.items()
        if selection.get("selectionType") == "category"
    }


def _find_group_by_key(scanned_groups: list[dict], group_key: str) -> dict | None:
    return next((group for group in scanned_groups if group["groupKey"] == group_key), None)


def _target_ledger_account(tracked_accounts: dict[str, dict], target_tracked_account_id: str) -> str | None:
    target_account = tracked_accounts.get(target_tracked_account_id, {})
    return str(target_account.get("ledger_account", "")).strip() or None


def _target_requires_import_match(tracked_accounts: dict[str, dict], target_tracked_account_id: str) -> bool:
    target_account = tracked_accounts.get(target_tracked_account_id, {})
    return bool(str(target_account.get("import_account_id", "")).strip())


def _build_operation(
    *,
    group_key: str,
    transaction_start_line: int,
    transaction_end_line: int,
    posting_line_no: int | None,
    target_account: str | None,
    expected_unknown: bool,
    metadata_updates: dict[str, str | None],
) -> dict:
    return {
        "groupKey": group_key,
        "transactionStartLine": transaction_start_line,
        "transactionEndLine": transaction_end_line,
        "postingUpdates": (
            [
                {
                    "postingLineNo": posting_line_no,
                    "targetAccount": target_account,
                    "expectedUnknown": expected_unknown,
                }
            ]
            if posting_line_no is not None and target_account is not None
            else []
        ),
        "metadataUpdates": metadata_updates,
    }


def _queue_operation(operations_by_start: dict[int, dict], operation: dict) -> None:
    existing = operations_by_start.get(operation["transactionStartLine"])
    if existing is None:
        operations_by_start[operation["transactionStartLine"]] = operation
        return

    existing["postingUpdates"].extend(operation.get("postingUpdates", []))
    existing["metadataUpdates"].update(operation.get("metadataUpdates", {}))


def _apply_operation(lines: list[str], operation: dict) -> tuple[list[str], str | None]:
    start_idx = operation["transactionStartLine"] - 1
    end_idx = operation["transactionEndLine"]
    if start_idx < 0 or end_idx > len(lines):
        return lines, f"Transaction starting at line {operation['transactionStartLine']} is no longer available"

    txn_lines = list(lines[start_idx:end_idx])
    for posting_update in operation.get("postingUpdates", []):
        posting_line_no = posting_update["postingLineNo"]
        relative_index = posting_line_no - operation["transactionStartLine"]
        if relative_index < 0 or relative_index >= len(txn_lines):
            return lines, f"Line {posting_line_no} is no longer part of this transaction"
        line = txn_lines[relative_index]
        match = ACCOUNT_LINE_RE.match(line) or ACCOUNT_ONLY_RE.match(line)
        if not match:
            return lines, f"Line {posting_line_no} is no longer a posting"
        if posting_update.get("expectedUnknown") and "Unknown" not in match.group(2):
            return lines, f"Line {posting_line_no} is already resolved"
        rewritten, replaced = rewrite_posting_account(line, posting_update["targetAccount"])
        if not replaced:
            return lines, f"Line {posting_line_no} could not be rewritten"
        txn_lines[relative_index] = rewritten

    txn_lines = upsert_transaction_metadata(txn_lines, operation.get("metadataUpdates", {}))
    updated_lines = list(lines)
    updated_lines[start_idx:end_idx] = txn_lines
    return updated_lines, None


def apply_unknown_mappings(
    journal_path: Path,
    accounts_dat: Path,
    selections: dict[str, dict],
    scanned_groups: list[dict],
    tracked_accounts: dict[str, dict],
) -> tuple[int, list[dict]]:
    category_selections = _stage_category_selections(selections)
    known_accounts = _load_known_accounts(accounts_dat)
    invalid = sorted({acct for acct in category_selections.values() if acct and acct not in known_accounts})
    if invalid:
        raise ValueError(f"Unknown account(s): {', '.join(invalid)}")

    warnings: list[dict] = []
    original_lines = journal_path.read_text(encoding="utf-8").splitlines()
    operations_by_start: dict[int, dict] = {}
    processed_line_nos: set[int] = set()

    # Transfer selections win because one accepted transfer may resolve its counterpart automatically.
    for group in scanned_groups:
        selection = selections.get(group["groupKey"])
        if not selection or selection.get("selectionType") != "transfer":
            continue

        target_tracked_account_id = str(selection.get("targetTrackedAccountId", "")).strip()
        if not target_tracked_account_id:
            continue
        if target_tracked_account_id not in tracked_accounts:
            warnings.append({"groupKey": group["groupKey"], "warning": f"Unknown tracked account: {target_tracked_account_id}"})
            continue

        target_ledger_account = _target_ledger_account(tracked_accounts, target_tracked_account_id)
        target_requires_import_match = _target_requires_import_match(tracked_accounts, target_tracked_account_id)
        if not target_ledger_account:
            warnings.append(
                {
                    "groupKey": group["groupKey"],
                    "warning": f"Tracked account {target_tracked_account_id} is missing a ledger account",
                }
            )
            continue

        for txn in group["txns"]:
            if txn["lineNo"] in processed_line_nos:
                continue

            source_tracked_account_id = str(txn.get("sourceTrackedAccountId") or "").strip()
            if not source_tracked_account_id:
                warnings.append(
                    {"groupKey": group["groupKey"], "warning": f"Transaction on line {txn['lineNo']} does not have a tracked source account"}
                )
                continue
            if source_tracked_account_id == target_tracked_account_id:
                warnings.append(
                    {"groupKey": group["groupKey"], "warning": f"Transfer on line {txn['lineNo']} cannot target the same tracked account"}
                )
                continue

            suggestion = txn.get("transferSuggestion") or {}
            matched_suggestion = (
                suggestion
                if str(suggestion.get("targetTrackedAccountId") or "").strip() == target_tracked_account_id
                else None
            )

            if not target_requires_import_match:
                _queue_operation(
                    operations_by_start,
                    _build_operation(
                        group_key=group["groupKey"],
                        transaction_start_line=int(txn["transactionStartLine"]),
                        transaction_end_line=int(txn["transactionEndLine"]),
                        posting_line_no=int(txn["lineNo"]),
                        target_account=target_ledger_account,
                        expected_unknown=True,
                        metadata_updates={
                            "transfer_id": None,
                            "transfer_state": None,
                            "transfer_peer_account_id": None,
                        },
                    ),
                )
                processed_line_nos.add(int(txn["lineNo"]))
                continue

            transfer_account = ensure_transfer_account(accounts_dat, source_tracked_account_id, target_tracked_account_id)
            transfer_id = str(uuid4().hex)
            current_state = "pending"

            if matched_suggestion:
                current_state = "matched"
                if matched_suggestion.get("candidateState") == "pending":
                    transfer_id = str(matched_suggestion.get("candidateTransferId") or transfer_id)
                    transfer_metadata = {
                        "transfer_id": transfer_id,
                        "transfer_state": "matched",
                        "transfer_peer_account_id": source_tracked_account_id,
                    }
                    _queue_operation(
                        operations_by_start,
                        _build_operation(
                            group_key=group["groupKey"],
                            transaction_start_line=int(matched_suggestion["candidateTransactionStartLine"]),
                            transaction_end_line=int(matched_suggestion["candidateTransactionEndLine"]),
                            posting_line_no=None,
                            target_account=None,
                            expected_unknown=False,
                            metadata_updates=transfer_metadata,
                        ),
                    )
                else:
                    candidate_group_key = str(matched_suggestion.get("candidateGroupKey") or "")
                    candidate_group = _find_group_by_key(scanned_groups, candidate_group_key) if candidate_group_key else None
                    candidate_txn = next(
                        (
                            item
                            for item in (candidate_group.get("txns", []) if candidate_group else [])
                            if item["txnId"] == matched_suggestion.get("candidateTxnId")
                        ),
                        None,
                    )
                    if candidate_txn is None:
                        warnings.append(
                            {
                                "groupKey": group["groupKey"],
                                "warning": f"Suggested transfer counterpart for line {txn['lineNo']} is no longer available",
                            }
                        )
                        continue
                    _queue_operation(
                        operations_by_start,
                        _build_operation(
                            group_key=group["groupKey"],
                            transaction_start_line=int(candidate_txn["transactionStartLine"]),
                            transaction_end_line=int(candidate_txn["transactionEndLine"]),
                            posting_line_no=int(candidate_txn["lineNo"]),
                            target_account=transfer_account,
                            expected_unknown=True,
                            metadata_updates={
                                "transfer_id": transfer_id,
                                "transfer_state": "matched",
                                "transfer_peer_account_id": source_tracked_account_id,
                            },
                        ),
                    )
                    processed_line_nos.add(int(candidate_txn["lineNo"]))

            _queue_operation(
                operations_by_start,
                _build_operation(
                    group_key=group["groupKey"],
                    transaction_start_line=int(txn["transactionStartLine"]),
                    transaction_end_line=int(txn["transactionEndLine"]),
                    posting_line_no=int(txn["lineNo"]),
                    target_account=transfer_account,
                    expected_unknown=True,
                    metadata_updates={
                        "transfer_id": transfer_id,
                        "transfer_state": current_state,
                        "transfer_peer_account_id": target_tracked_account_id,
                    },
                ),
            )
            processed_line_nos.add(int(txn["lineNo"]))

    for group in scanned_groups:
        selection = selections.get(group["groupKey"])
        if not selection or selection.get("selectionType") != "category":
            continue
        category_account = str(selection.get("categoryAccount", "")).strip()
        if not category_account:
            continue
        for txn in group["txns"]:
            if txn["lineNo"] in processed_line_nos:
                warnings.append(
                    {
                        "groupKey": group["groupKey"],
                        "warning": f"Line {txn['lineNo']} was already resolved as the matched side of a transfer",
                    }
                )
                continue
            _queue_operation(
                operations_by_start,
                _build_operation(
                    group_key=group["groupKey"],
                    transaction_start_line=int(txn["transactionStartLine"]),
                    transaction_end_line=int(txn["transactionEndLine"]),
                    posting_line_no=int(txn["lineNo"]),
                    target_account=category_account,
                    expected_unknown=True,
                    metadata_updates={},
                ),
            )
            processed_line_nos.add(int(txn["lineNo"]))

    lines = list(original_lines)
    applied_count = 0
    for _, operation in sorted(operations_by_start.items(), key=lambda item: item[0], reverse=True):
        lines, warning = _apply_operation(lines, operation)
        if warning is not None:
            warnings.append({"groupKey": operation["groupKey"], "warning": warning})
            continue
        applied_count += 1

    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return applied_count, warnings


def _remove_payee_rule_lines(lines: list[str], payee_key: str) -> list[str]:
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("payee "):
            existing_payee = stripped[len("payee "):].strip().lower()
            if existing_payee == payee_key:
                continue
        kept.append(line)
    return kept


def add_payee_rule(accounts_dat: Path, payee: str, account: str) -> tuple[bool, str | None]:
    known_accounts = _load_known_accounts(accounts_dat)
    if account not in known_accounts:
        raise ValueError(f"Unknown account: {account}")

    payee_clean = payee.strip()
    if not payee_clean:
        raise ValueError("Payee is required")

    rules_lines = accounts_dat.read_text(encoding="utf-8").splitlines()
    existing = _load_payee_rules(accounts_dat)
    key = payee_clean.lower()

    existing_account = existing.get(key)
    if existing_account == account:
        return False, None

    # Support rule edits by replacing existing payee mapping with the new target.
    if existing_account is not None:
        rules_lines = _remove_payee_rule_lines(rules_lines, key)

    insert_at = None
    for i, line in enumerate(rules_lines):
        if line.startswith("account ") and line[len("account "):].strip() == account:
            insert_at = i + 1
            while insert_at < len(rules_lines) and not rules_lines[insert_at].startswith("account "):
                insert_at += 1
            break

    if insert_at is None:
        return False, f"Target account block not found: {account}"

    rule_line = f"\tpayee {payee_clean}"
    rules_lines.insert(insert_at, rule_line)
    accounts_dat.write_text("\n".join(rules_lines) + "\n", encoding="utf-8")
    return True, None


def _infer_account_type(account: str) -> str:
    prefix = account.split(":", 1)[0].strip().lower()
    if prefix == "assets":
        return "Asset"
    if prefix in {"liabilities", "liability"}:
        return "Liability"
    if prefix in {"expenses", "expense"}:
        return "Expense"
    if prefix in {"income", "revenue"}:
        return "Revenue"
    if prefix == "equity":
        return "Equity"
    return "Other"


def create_account(
    accounts_dat: Path,
    account: str,
    account_type: str | None = None,
    description: str | None = None,
) -> tuple[bool, str | None]:
    account_clean = account.strip()
    if not account_clean:
        raise ValueError("Account is required")
    if ":" not in account_clean:
        raise ValueError("Account must be fully qualified, e.g. Expenses:Food")

    known = _load_known_accounts(accounts_dat)
    if account_clean in known:
        return False, None

    account_type_clean = (account_type or "").strip() or _infer_account_type(account_clean)
    description_clean = re.sub(r"\s*[\r\n]+\s*", " ", description or "").strip()
    if accounts_dat.exists():
        lines = accounts_dat.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"account {account_clean}")
    lines.append(f"    ; type: {account_type_clean}")
    if description_clean:
        lines.append(f"    ; description: {description_clean}")
    accounts_dat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, None
