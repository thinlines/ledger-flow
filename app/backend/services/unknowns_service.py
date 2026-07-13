from __future__ import annotations

from .journal_query_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE, META_RE, TXN_START_RE
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .archive_service import archive_manual_entry, rollback_archive
from .config_service import infer_account_kind
from .merchant_service import Merchant
from .manual_entry_service import (
    _extract_user_metadata_lines,
    _parse_manual_entry_destination,
    has_manual_tag,
    populate_match_candidates,
)
from .rules_service import extract_set_account, find_matching_rule
from .transfer_service import (
    MAX_TRANSFER_MATCH_DAYS,
    TRANSFER_MATCH_STATE_MATCHED,
    TRANSFER_MATCH_STATE_PENDING,
    build_direct_transfer_metadata_updates,
    build_import_match_transfer_metadata_updates,
    clear_transfer_metadata_updates,
    ensure_transfer_account,
    infer_blank_posting_amounts,
    parse_transfer_metadata,
    parse_amount,
    rewrite_posting_account,
    upsert_transaction_metadata,
)

from .header_parser import HEADER_RE
from .journal_block_service import (
    hash_block as _hash_block,
    locate_block_by_id as _locate_block_by_id,
)

def _block_has_match_id_tag(lines: list[str]) -> bool:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(";") and (
            "match-id:" in stripped or "lf_match_id:" in stripped
        ):
            return True
    return False


def _iter_transaction_ranges(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines) if TXN_START_RE.match(line)]
    ranges: list[tuple[int, int]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        ranges.append((start, end))
    return ranges


def _rebase_record(lines: list[str], record: dict) -> tuple[dict | None, str | None]:
    """Re-locate a scanned transaction record against the current file.

    Blocks carrying an ``lf_txn_id`` are found by identity and rejected only
    on true block-level staleness (content-hash mismatch) — line shifts from
    earlier edits rebase all positional fields instead of failing. Blocks
    without identity keep the byte-exact positional check.

    Returns ``(rebased_record, None)`` or ``(None, warning_text)``.
    """
    lf_txn_id = str(record.get("lfTxnId") or "").strip()
    if lf_txn_id:
        located = _locate_block_by_id(lines, lf_txn_id)
        if located is None:
            return None, "This transaction no longer exists in the journal (stale data — try refreshing)"
        start, end = located
        if _hash_block(lines, start, end) != record.get("blockHash"):
            return None, "This transaction changed since it was scanned — refresh and try again"
        delta = (start + 1) - int(record["transactionStartLine"])
        rebased = {**record, "transactionStartLine": start + 1, "transactionEndLine": end}
        if record.get("lineNo") is not None:
            rebased["lineNo"] = int(record["lineNo"]) + delta
        return rebased, None

    start = int(record["transactionStartLine"]) - 1
    end = int(record["transactionEndLine"])
    if start < 0 or end > len(lines) or _hash_block(lines, start, end) != record.get("blockHash"):
        return None, "This transaction changed since it was scanned (stale data — try refreshing)"
    return record, None


def _parse_postings(lines: list[str], start: int, end: int) -> list[dict]:
    postings = []
    for i in range(start + 1, end):
        line = lines[i]
        if line.lstrip().startswith(";"):
            continue

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
    source_identity = str(metadata.get("lf_source_identity", "")).strip()
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
        match = HEADER_RE.match(lines[start])
        if match:
            current_date = match.group("date")
            current_payee = match.group("payee").strip() or "(no payee)"
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
        transfer = parse_transfer_metadata(metadata, tracked_accounts)
        base_txn_id = _transaction_base_id(journal_path, start + 1, metadata)
        record = {
            "txnId": base_txn_id,
            "lfTxnId": str(metadata.get("lf_txn_id", "")).strip() or None,
            "blockHash": _hash_block(lines, start, end),
            "payeeDisplay": current_payee,
            "date": current_date,
            "postedOn": _parse_posted_on(current_date),
            "transactionStartLine": start + 1,
            "transactionEndLine": end,
            "unknownPostingCount": len(unknown_postings),
            "postings": postings,
            "metadata": metadata,
            "transferId": transfer.transfer_id,
            "transferType": transfer.transfer_type,
            "transferMatchState": transfer.transfer_match_state,
            "transferState": transfer.transfer_state_for_ui,
            "transferPeerAccountId": transfer.peer_account_id,
            "hasTransferMetadata": transfer.has_any_transfer_metadata,
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
                "lfTxnId": record["lfTxnId"],
                "blockHash": record["blockHash"],
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
        "candidateLfTxnId": candidate.get("lfTxnId"),
        "candidateBlockHash": candidate.get("blockHash"),
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
        and not record.get("hasTransferMetadata")
    ]
    pending_transfers = [
        record
        for record in transaction_records
        if record.get("transferType") == "import_match"
        and record.get("transferMatchState") == "pending"
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
        for row in current.get("unknownRows", []):
            row["transferMatchCount"] = len(matches)


def scan_unknowns(
    journal_path: Path,
    rules: list[dict],
    import_accounts: dict[str, dict] | None = None,
    tracked_accounts: dict[str, dict] | None = None,
    merchants: list[Merchant] | None = None,
) -> dict:
    transaction_records, groups = _build_transaction_records(
        journal_path,
        import_accounts or {},
        tracked_accounts or {},
    )
    _populate_transfer_suggestions(transaction_records)
    populate_match_candidates(groups, journal_path, import_accounts or {}, tracked_accounts or {})

    for group in groups:
        for txn in group["txns"]:
            matched = find_matching_rule(
                {
                    "payee": group["payeeDisplay"],
                    "merchant": group["payeeDisplay"],
                    "date": txn["date"].replace("/", "-"),
                    "amount": txn["amount"],
                    "account": txn["currentAccount"],
                    "accounts": [
                        txn["currentAccount"],
                        txn["counterpartyAccount"],
                        group["sourceLedgerAccount"],
                    ],
                },
                rules,
            )
            group["_matchSignatures"].append(
                (
                    matched["id"] if matched else None,
                    extract_set_account(matched) if matched else None,
                    matched["conditions"][0]["value"] if matched else None,
                )
            )

    defaults_by_merchant = {
        merchant.name: merchant.default_account
        for merchant in merchants or []
        if merchant.default_account
    }
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

        # Categorization precedence: rule → merchant default account.
        if group["suggestedAccount"] is not None:
            group["suggestedSource"] = "rule"
        elif defaults_by_merchant.get(group["payeeDisplay"]):
            group["suggestedAccount"] = defaults_by_merchant[group["payeeDisplay"]]
            group["suggestedSource"] = "merchant"
        else:
            group["suggestedSource"] = None

    return {"groups": groups}


def _stage_category_selections(selections: dict[str, dict]) -> dict[str, str]:
    return {
        txn_id: str(selection.get("categoryAccount", "")).strip()
        for txn_id, selection in selections.items()
        if selection.get("selectionType") == "category"
    }


def _index_txns_by_id(scanned_groups: list[dict]) -> dict[str, tuple[dict, dict]]:
    """Map ``txnId`` to ``(group, txn)`` for selection lookup."""
    return {
        txn["txnId"]: (group, txn)
        for group in scanned_groups
        for txn in group["txns"]
    }


def _find_group_by_key(scanned_groups: list[dict], group_key: str) -> dict | None:
    return next((group for group in scanned_groups if group["groupKey"] == group_key), None)


def _target_ledger_account(tracked_accounts: dict[str, dict], target_tracked_account_id: str) -> str | None:
    target_account = tracked_accounts.get(target_tracked_account_id, {})
    return str(target_account.get("ledger_account", "")).strip() or None


def _target_requires_import_match(tracked_accounts: dict[str, dict], target_tracked_account_id: str) -> bool:
    target_account = tracked_accounts.get(target_tracked_account_id, {})
    import_account_id = target_account.get("import_account_id")
    return bool(str(import_account_id or "").strip())


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
        return lines, "This transaction is no longer available (changed since it was scanned)"

    txn_lines = list(lines[start_idx:end_idx])
    for posting_update in operation.get("postingUpdates", []):
        posting_line_no = posting_update["postingLineNo"]
        relative_index = posting_line_no - operation["transactionStartLine"]
        if relative_index < 0 or relative_index >= len(txn_lines):
            return lines, "A posting in this transaction changed since it was scanned"
        line = txn_lines[relative_index]
        match = ACCOUNT_LINE_RE.match(line) or ACCOUNT_ONLY_RE.match(line)
        if not match:
            return lines, "A posting in this transaction changed since it was scanned"
        if posting_update.get("expectedUnknown") and "Unknown" not in match.group(2):
            return lines, "This transaction is already resolved"
        rewritten, replaced = rewrite_posting_account(line, posting_update["targetAccount"])
        if not replaced:
            return lines, "A posting in this transaction could not be rewritten"
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
    warnings: list[dict] = []
    original_lines = journal_path.read_text(encoding="utf-8").splitlines()
    operations_by_start: dict[int, dict] = {}
    processed_line_nos: set[int] = set()
    txn_index = _index_txns_by_id(scanned_groups)

    # Resolve each selection to its (group, txn) and re-locate the block in
    # the current file by its lf_txn_id (#17): line shifts from earlier edits
    # rebase the staged positions; only a changed or deleted block is stale.
    resolved_selections: list[tuple[str, dict, dict, dict]] = []
    for txn_id, selection in selections.items():
        entry = txn_index.get(txn_id)
        if entry is None:
            warnings.append({"txnId": txn_id, "warning": "Transaction is no longer in this stage"})
            continue
        group, txn = entry
        rebased, stale_warning = _rebase_record(original_lines, txn)
        if rebased is None:
            warnings.append(
                {"txnId": txn_id, "groupKey": group["groupKey"], "warning": stale_warning}
            )
            continue
        resolved_selections.append((txn_id, selection, group, rebased))

    # Pass 1: transfers. Accepted transfers may resolve their counterpart, so
    # they run before category and match selections.
    for txn_id, selection, group, txn in resolved_selections:
        if selection.get("selectionType") != "transfer":
            continue
        if txn["lineNo"] in processed_line_nos:
            continue

        target_tracked_account_id = str(selection.get("targetTrackedAccountId", "")).strip()
        if not target_tracked_account_id:
            continue
        if target_tracked_account_id not in tracked_accounts:
            warnings.append(
                {"txnId": txn_id, "groupKey": group["groupKey"], "warning": f"Unknown tracked account: {target_tracked_account_id}"}
            )
            continue

        target_ledger_account = _target_ledger_account(tracked_accounts, target_tracked_account_id)
        target_requires_import_match = _target_requires_import_match(tracked_accounts, target_tracked_account_id)
        if not target_ledger_account:
            warnings.append(
                {
                    "txnId": txn_id,
                    "groupKey": group["groupKey"],
                    "warning": f"Tracked account {target_tracked_account_id} is missing a ledger account",
                }
            )
            continue

        source_tracked_account_id = str(txn.get("sourceTrackedAccountId") or "").strip()
        if not source_tracked_account_id:
            warnings.append(
                {"txnId": txn_id, "groupKey": group["groupKey"], "warning": f"Transaction on line {txn['lineNo']} does not have a tracked source account"}
            )
            continue
        if source_tracked_account_id == target_tracked_account_id:
            warnings.append(
                {"txnId": txn_id, "groupKey": group["groupKey"], "warning": f"Transfer on line {txn['lineNo']} cannot target the same tracked account"}
            )
            continue

        suggestion = txn.get("transferSuggestion") or {}
        matched_suggestion = (
            suggestion
            if str(suggestion.get("targetTrackedAccountId") or "").strip() == target_tracked_account_id
            else None
        )

        if not target_requires_import_match:
            transfer_id = str(txn.get("transferId") or "").strip() or str(uuid4().hex)
            _queue_operation(
                operations_by_start,
                _build_operation(
                    group_key=group["groupKey"],
                    transaction_start_line=int(txn["transactionStartLine"]),
                    transaction_end_line=int(txn["transactionEndLine"]),
                    posting_line_no=int(txn["lineNo"]),
                    target_account=target_ledger_account,
                    expected_unknown=True,
                    metadata_updates=build_direct_transfer_metadata_updates(
                        transfer_id=transfer_id,
                        peer_account_id=target_tracked_account_id,
                    ),
                ),
            )
            processed_line_nos.add(int(txn["lineNo"]))
            continue

        transfer_account = ensure_transfer_account(accounts_dat, source_tracked_account_id, target_tracked_account_id)
        transfer_id = str(txn.get("transferId") or "").strip() or str(uuid4().hex)
        current_state = TRANSFER_MATCH_STATE_PENDING

        if matched_suggestion:
            current_state = TRANSFER_MATCH_STATE_MATCHED
            if matched_suggestion.get("candidateState") == "pending":
                transfer_id = str(matched_suggestion.get("candidateTransferId") or transfer_id)
                transfer_metadata = build_import_match_transfer_metadata_updates(
                    transfer_id=transfer_id,
                    peer_account_id=source_tracked_account_id,
                    transfer_match_state=TRANSFER_MATCH_STATE_MATCHED,
                )
                candidate_record, candidate_warning = _rebase_record(
                    original_lines,
                    {
                        "lfTxnId": matched_suggestion.get("candidateLfTxnId"),
                        "blockHash": matched_suggestion.get("candidateBlockHash"),
                        "transactionStartLine": int(matched_suggestion["candidateTransactionStartLine"]),
                        "transactionEndLine": int(matched_suggestion["candidateTransactionEndLine"]),
                    },
                )
                if candidate_record is None:
                    warnings.append(
                        {"txnId": txn_id, "groupKey": group["groupKey"], "warning": candidate_warning}
                    )
                    continue
                _queue_operation(
                    operations_by_start,
                    _build_operation(
                        group_key=group["groupKey"],
                        transaction_start_line=int(candidate_record["transactionStartLine"]),
                        transaction_end_line=int(candidate_record["transactionEndLine"]),
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
                            "txnId": txn_id,
                            "groupKey": group["groupKey"],
                            "warning": "The suggested transfer counterpart is no longer available",
                        }
                    )
                    continue
                candidate_txn, candidate_warning = _rebase_record(original_lines, candidate_txn)
                if candidate_txn is None:
                    warnings.append(
                        {"txnId": txn_id, "groupKey": group["groupKey"], "warning": candidate_warning}
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
                        metadata_updates=build_import_match_transfer_metadata_updates(
                            transfer_id=transfer_id,
                            peer_account_id=source_tracked_account_id,
                            transfer_match_state=TRANSFER_MATCH_STATE_MATCHED,
                        ),
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
                metadata_updates=build_import_match_transfer_metadata_updates(
                    transfer_id=transfer_id,
                    peer_account_id=target_tracked_account_id,
                    transfer_match_state=current_state,
                ),
            ),
        )
        processed_line_nos.add(int(txn["lineNo"]))

    # Pass 2: per-txn category assignments.
    for txn_id, selection, group, txn in resolved_selections:
        if selection.get("selectionType") != "category":
            continue
        category_account = str(selection.get("categoryAccount", "")).strip()
        if not category_account:
            continue
        if txn["lineNo"] in processed_line_nos:
            warnings.append(
                {
                    "txnId": txn_id,
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
                metadata_updates=clear_transfer_metadata_updates(),
            ),
        )
        processed_line_nos.add(int(txn["lineNo"]))

    # --- Match-apply section ---------------------------------------------
    # Matched manual entries are archived (not deleted) so a future unmatch can
    # restore them. The archive is linked 1:1 to the main-journal imported
    # transaction via a shared match-id UUID. Archive writes happen before
    # main-journal removal; on any failure from here through the journal write
    # we rollback the archive to its pre-apply size (or remove it if new).
    archived_path = journal_path.parent / "archived-manual.journal"
    archive_size_before = archived_path.stat().st_size if archived_path.exists() else None

    try:
        # Collect match selections per-txn. Multiple selections that point at
        # the same manual entry (same ``matchedManualLineRange``) share one
        # match-id and one archive write — the manual entry is removed once.
        manual_removal_ranges: list[tuple[int, int, str, str]] = []  # (start_idx, end_idx, group_key, match_id)
        match_tag_entries: list[tuple[int, str]] = []  # (0-indexed txn start line, match_id)
        match_ids_by_range: dict[tuple[int, int], str] = {}
        for txn_id, selection, group, txn in resolved_selections:
            if selection.get("selectionType") != "match":
                continue

            # Locate the manual entry by its lf_txn_id when the candidate
            # carried one (#17); the scan-time line range is the fallback
            # for id-less blocks.
            matched_manual_lf_txn_id = str(selection.get("matchedManualLfTxnId") or "").strip()
            if matched_manual_lf_txn_id:
                located_manual = _locate_block_by_id(original_lines, matched_manual_lf_txn_id)
                if located_manual is None:
                    warnings.append({"txnId": txn_id, "groupKey": group["groupKey"], "warning": "The matched manual entry no longer exists (stale data — try refreshing)"})
                    continue
                manual_start = located_manual[0] + 1
                manual_end = located_manual[1]
                # Trim trailing blank lines from the range, mirroring the
                # scan-time candidate ranges.
                while manual_end > manual_start and not original_lines[manual_end - 1].strip():
                    manual_end -= 1
            else:
                matched_manual_line_range = selection.get("matchedManualLineRange")
                if not matched_manual_line_range or len(matched_manual_line_range) < 2:
                    warnings.append({"txnId": txn_id, "groupKey": group["groupKey"], "warning": "Match selection is missing the manual entry's identity"})
                    continue

                manual_start = int(matched_manual_line_range[0])
                manual_end = int(matched_manual_line_range[1])

                if manual_start < 1 or manual_end > len(original_lines):
                    warnings.append({"txnId": txn_id, "groupKey": group["groupKey"], "warning": "The matched manual entry is no longer available (stale data — try refreshing)"})
                    continue

            manual_lines = original_lines[manual_start - 1 : manual_end]
            if not has_manual_tag(manual_lines):
                warnings.append({"txnId": txn_id, "groupKey": group["groupKey"], "warning": "Manual entry is no longer available (missing :manual: tag)"})
                continue

            source_ledger = group.get("sourceLedgerAccount", "")
            destination = _parse_manual_entry_destination(manual_lines, source_ledger)
            if not destination:
                warnings.append({"txnId": txn_id, "groupKey": group["groupKey"], "warning": "Manual entry does not have a usable destination account"})
                continue

            user_metadata_lines = _extract_user_metadata_lines(manual_lines)
            metadata_updates: dict[str, str | None] = {}
            for meta_line in user_metadata_lines:
                mm = META_RE.match(meta_line)
                if mm:
                    metadata_updates[mm.group(1).strip().lower()] = mm.group(2).strip()

            range_key = (manual_start, manual_end)
            match_id = match_ids_by_range.get(range_key)
            if match_id is None:
                match_id = f"match_{uuid4()}"
                match_ids_by_range[range_key] = match_id
                manual_removal_ranges.append((manual_start - 1, manual_end, group["groupKey"], match_id))
            selection["matchId"] = match_id
            selection["importedTxnId"] = str(txn.get("lfTxnId") or txn_id)
            selection["archivedManualTxnId"] = matched_manual_lf_txn_id
            selection["originalManualBlock"] = "\n".join(manual_lines)
            selection["originalImportedBlock"] = "\n".join(
                original_lines[
                    int(txn["transactionStartLine"]) - 1 : int(txn["transactionEndLine"])
                ]
            )
            selection["manualInsertIndex"] = manual_start - 1
            selection["priorCategory"] = destination

            if txn["lineNo"] in processed_line_nos:
                warnings.append(
                    {"txnId": txn_id, "groupKey": group["groupKey"], "warning": f"Line {txn['lineNo']} was already resolved"}
                )
                continue

            _queue_operation(
                operations_by_start,
                _build_operation(
                    group_key=group["groupKey"],
                    transaction_start_line=int(txn["transactionStartLine"]),
                    transaction_end_line=int(txn["transactionEndLine"]),
                    posting_line_no=int(txn["lineNo"]),
                    target_account=destination,
                    expected_unknown=True,
                    metadata_updates=metadata_updates,
                ),
            )
            match_tag_entries.append((int(txn["transactionStartLine"]) - 1, match_id))
            processed_line_nos.add(int(txn["lineNo"]))

        lines = list(original_lines)
        applied_count = 0
        for _, operation in sorted(operations_by_start.items(), key=lambda item: item[0], reverse=True):
            lines, warning = _apply_operation(lines, operation)
            if warning is not None:
                warnings.append({"groupKey": operation["groupKey"], "warning": warning})
                continue
            applied_count += 1

        # Stamp matched imported transactions with :manual: and match-id: tags.
        # Convention: :manual: on line 2 of the block, match-id: on line 3.
        # :manual: marks the transaction as carrying its destination from a manual entry;
        # match-id: links it to the archived manual entry (used by a future unmatch).
        # Process in reverse order to preserve line indices as we insert.
        # Insertions both happen at start_idx+1, so inserting match-id FIRST and
        # :manual: SECOND yields the desired order header → :manual: → match-id → rest.
        # Dedup guards are defensive — tags should not already be present.
        for start_idx, match_id in sorted(set(match_tag_entries), key=lambda t: t[0], reverse=True):
            if start_idx >= len(lines):
                continue
            has_manual = False
            has_match_id = False
            for i in range(start_idx + 1, min(start_idx + 20, len(lines))):
                if TXN_START_RE.match(lines[i]):
                    break
                if ":manual:" in lines[i]:
                    has_manual = True
                if "match-id:" in lines[i] or "lf_match_id:" in lines[i]:
                    has_match_id = True
            if not has_match_id:
                lines.insert(start_idx + 1, f"    ; lf_match_id: {match_id}")
            if not has_manual:
                lines.insert(start_idx + 1, "    ; :manual:")
            block_end = next(
                (i for i in range(start_idx + 1, len(lines)) if TXN_START_RE.match(lines[i])),
                len(lines),
            )
            if not any("lf_txn_id:" in line for line in lines[start_idx + 1:block_end]):
                imported_txn_id = f"txn_{uuid4()}"
                lines.insert(start_idx + 1, f"    ; lf_txn_id: {imported_txn_id}")
                for selection in selections.values():
                    if selection.get("matchId") == match_id:
                        selection["importedTxnId"] = imported_txn_id

        # Archive then remove matched manual entries in reverse order to keep line indices stable.
        for start_idx, end_idx, group_key, match_id in sorted(manual_removal_ranges, key=lambda r: r[0], reverse=True):
            # Find the manual entry by scanning for :manual: tag near expected position.
            # Lines may have shifted due to metadata inserts and tag additions above.
            # A manual entry has :manual: AND no import_account_id. Matched imported
            # transactions also carry :manual: (inserted by this very flow) but have
            # import_account_id, so we must skip those to avoid removing the wrong record.
            found_start = None
            for i in range(max(0, start_idx - 10), min(len(lines), start_idx + 10)):
                if TXN_START_RE.match(lines[i]):
                    block_has_manual = False
                    block_has_import_account_id = False
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if TXN_START_RE.match(lines[j]):
                            break
                        if ":manual:" in lines[j]:
                            block_has_manual = True
                        if "import_account_id:" in lines[j]:
                            block_has_import_account_id = True
                    if block_has_manual and not block_has_import_account_id:
                        found_start = i
                        break

            if found_start is None:
                continue

            # Find the end of this transaction block.
            found_end = len(lines)
            for i in range(found_start + 1, len(lines)):
                if TXN_START_RE.match(lines[i]):
                    found_end = i
                    break

            # Extract the block content (without trailing blank lines) for archiving.
            archive_end = found_end
            while archive_end > found_start + 1 and not lines[archive_end - 1].strip():
                archive_end -= 1
            block_lines = lines[found_start:archive_end]

            # Archive the manual entry block before removal.
            # Edge case: a manual entry already carrying a match-id: tag implies a prior
            # match. Skip archive write (don't risk duplicating), surface a warning, and
            # continue with removal — strictly better than silent data loss.
            if _block_has_match_id_tag(block_lines):
                warnings.append({
                    "groupKey": group_key,
                    "warning": "Manual entry already carries a match-id tag; skipping archive write (possible prior match)",
                })
            else:
                archived_txn_id = archive_manual_entry(archived_path, match_id, block_lines)
                for selection in selections.values():
                    if selection.get("matchId") == match_id:
                        selection["archivedManualTxnId"] = archived_txn_id

            # Remove trailing blank lines from the main journal range (existing behavior).
            while found_end < len(lines) and not lines[found_end].strip():
                found_end += 1

            lines[found_start:found_end] = []

        journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        rollback_archive(archived_path, archive_size_before)
        raise

    return applied_count, warnings
