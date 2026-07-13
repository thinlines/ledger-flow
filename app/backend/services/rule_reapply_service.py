from __future__ import annotations

from .journal_query_service import ACCOUNT_LINE_RE, ACCOUNT_ONLY_RE
from pathlib import Path

from .config_service import AppConfig, infer_account_kind
from .journal_block_service import hash_block, locate_block_by_id
from .projection_service import load_projected_transaction_rows
from .rules_service import extract_set_account, find_matching_rule


def _scan_config(journal_path: Path) -> AppConfig:
    return AppConfig(journal_path.parent, journal_path.parent / "config.toml", {}, {
        "csv_dir": ".", "journal_dir": ".", "init_dir": ".",
        "opening_bal_dir": ".", "imports_dir": ".",
    }, {}, {})


def scan_rule_reapply(journal_path: Path, rule: dict, import_accounts: dict[str, dict], config: AppConfig | None = None) -> dict:
    target_account = extract_set_account(rule)
    if not target_account:
        raise ValueError("Rule must set an account before it can be applied to history.")

    candidates: list[dict] = []
    warnings: list[dict] = []
    matched_count = 0
    up_to_date_count = 0

    for transaction in load_projected_transaction_rows(config or _scan_config(journal_path), journal_path):
        current_date = transaction["date"].replace("/", "-")
        current_payee = transaction["payee"]
        metadata = transaction["metadata"]
        postings = transaction["postings"]
        if not find_matching_rule(
            {
                "payee": current_payee,
                "merchant": current_payee,
                "date": current_date,
                "accounts": [posting["account"] for posting in postings],
                "amounts": [posting["amount"] for posting in postings],
            },
            [rule],
        ):
            continue

        matched_count += 1
        import_account_id = metadata.get("import_account_id") or None
        if not import_account_id:
            warnings.append(
                {
                    "date": current_date,
                    "payee": current_payee,
                    "reason": "Skipped manual transaction because it is not linked to an import account.",
                }
            )
            continue

        import_account_cfg = import_accounts.get(import_account_id, {})
        source_ledger_account = str(import_account_cfg.get("ledger_account", "")).strip()
        if not source_ledger_account:
            warnings.append(
                {
                    "date": current_date,
                    "payee": current_payee,
                    "reason": f"Skipped transaction because import account {import_account_id} is not configured.",
                }
            )
            continue

        category_postings = [posting for posting in postings if posting["account"] != source_ledger_account]
        if len(category_postings) != 1:
            warnings.append(
                {
                    "date": current_date,
                    "payee": current_payee,
                    "reason": "Skipped split or ambiguous transaction because it does not have a single category posting.",
                }
            )
            continue

        posting = category_postings[0]
        if infer_account_kind(posting["account"]) not in {"expense", "income"}:
            warnings.append(
                {
                    "date": current_date,
                    "payee": current_payee,
                    "reason": "Skipped transfer or balance movement because the matched posting is not an income or expense category.",
                }
            )
            continue

        if posting["account"] == target_account:
            up_to_date_count += 1
            continue

        candidates.append(
            {
                "id": f"{journal_path.name}:{posting['lineNo']}",
                "lfTxnId": str(metadata.get("lf_txn_id", "")).strip() or None,
                "blockHash": transaction["blockHash"],
                "transactionStartLine": transaction["transactionStartLine"],
                "date": current_date,
                "payee": current_payee,
                "amount": posting["amount"],
                "lineNo": posting["lineNo"],
                "currentAccount": posting["account"],
                "targetAccount": target_account,
                "importAccountId": import_account_id,
                "sourceAccountLabel": str(import_account_cfg.get("display_name", import_account_id)),
                "sourceLedgerAccount": source_ledger_account,
            }
        )

    return {
        "targetAccount": target_account,
        "candidates": candidates,
        "warnings": warnings,
        "summary": {
            "matchedCount": matched_count,
            "candidateCount": len(candidates),
            "upToDateCount": up_to_date_count,
            "skippedCount": len(warnings),
        },
    }


def apply_rule_reapply(
    journal_path: Path,
    accounts_dat: Path,
    candidates: list[dict],
    selected_candidate_ids: list[str],
) -> tuple[int, list[dict]]:
    if not selected_candidate_ids:
        raise ValueError("No historical matches were selected.")

    selected_ids = set(selected_candidate_ids)
    selected_candidates = [candidate for candidate in candidates if candidate["id"] in selected_ids]
    missing_ids = sorted(selected_ids - {candidate["id"] for candidate in selected_candidates})
    if missing_ids:
        raise ValueError("Some selected historical matches are no longer available.")

    warnings: list[dict] = []
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    updated_count = 0

    for candidate in selected_candidates:
        # Re-locate the block by lf_txn_id (#17): line shifts from earlier
        # edits rebase the staged posting position; only a changed or
        # deleted block is stale.
        idx = int(candidate["lineNo"]) - 1
        lf_txn_id = str(candidate.get("lfTxnId") or "").strip()
        if lf_txn_id:
            located = locate_block_by_id(lines, lf_txn_id)
            if located is None:
                warnings.append(
                    {
                        "candidateId": candidate["id"],
                        "warning": "This transaction no longer exists in the journal (stale data — try refreshing).",
                    }
                )
                continue
            start, end = located
            if hash_block(lines, start, end) != candidate.get("blockHash"):
                warnings.append(
                    {
                        "candidateId": candidate["id"],
                        "warning": "This transaction changed since the scan and was skipped.",
                    }
                )
                continue
            idx += (start + 1) - int(candidate["transactionStartLine"])

        if idx < 0 or idx >= len(lines):
            warnings.append(
                {
                    "candidateId": candidate["id"],
                    "warning": "This transaction is no longer available (stale data — try refreshing).",
                }
            )
            continue

        line = lines[idx]
        match = ACCOUNT_LINE_RE.match(line)
        if match:
            current_account = match.group(2).strip()
            if current_account != candidate["currentAccount"]:
                warnings.append(
                    {
                        "candidateId": candidate["id"],
                        "warning": "This transaction changed since the scan and was skipped.",
                    }
                )
                continue
            lines[idx] = f"{match.group(1)}{candidate['targetAccount']}{match.group(3)}{match.group(4)}"
            updated_count += 1
            continue

        match = ACCOUNT_ONLY_RE.match(line)
        if match:
            current_account = match.group(2).strip()
            if current_account != candidate["currentAccount"]:
                warnings.append(
                    {
                        "candidateId": candidate["id"],
                        "warning": "This transaction changed since the scan and was skipped.",
                    }
                )
                continue
            lines[idx] = f"{match.group(1)}{candidate['targetAccount']}"
            updated_count += 1
            continue

        warnings.append(
            {
                "candidateId": candidate["id"],
                "warning": "A posting in this transaction changed since the scan.",
            }
        )

    if updated_count > 0:
        journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return updated_count, warnings
