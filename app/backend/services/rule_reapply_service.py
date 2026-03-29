from __future__ import annotations

import re
from pathlib import Path

from .config_service import infer_account_kind
from .rules_service import extract_set_account, find_matching_rule
from .unknowns_service import list_known_accounts


from .header_parser import HEADER_RE

ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
ACCOUNT_ONLY_RE = re.compile(r"^(\s+)([^\s].*?)\s*$")
META_RE = re.compile(r"^\s*;\s*([^:]+):\s*(.*)$")
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")


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
        match = ACCOUNT_LINE_RE.match(line)
        if match:
            postings.append(
                {
                    "lineNo": i + 1,
                    "indent": match.group(1),
                    "account": match.group(2).strip(),
                    "sep": match.group(3),
                    "amount": match.group(4).strip(),
                }
            )
            continue

        if line.lstrip().startswith(";"):
            continue

        match = ACCOUNT_ONLY_RE.match(line)
        if not match:
            continue

        postings.append(
            {
                "lineNo": i + 1,
                "indent": match.group(1),
                "account": match.group(2).strip(),
                "sep": "",
                "amount": "",
            }
        )
    return postings


def _parse_metadata(lines: list[str], start: int, end: int) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for i in range(start + 1, end):
        match = META_RE.match(lines[i])
        if match:
            metadata[match.group(1).strip().lower()] = match.group(2).strip()
    return metadata


def scan_rule_reapply(journal_path: Path, rule: dict, import_accounts: dict[str, dict]) -> dict:
    target_account = extract_set_account(rule)
    if not target_account:
        raise ValueError("Rule must set an account before it can be applied to history.")

    lines = journal_path.read_text(encoding="utf-8").splitlines()
    candidates: list[dict] = []
    warnings: list[dict] = []
    matched_count = 0
    up_to_date_count = 0

    for start, end in _iter_transaction_ranges(lines):
        header_match = HEADER_RE.match(lines[start])
        if header_match:
            current_date = header_match.group("date").replace("/", "-")
            current_payee = header_match.group("payee").strip() or "(no payee)"
        else:
            current_date = ""
            current_payee = "(no payee)"

        if not find_matching_rule({"payee": current_payee, "date": current_date}, [rule]):
            continue

        matched_count += 1
        metadata = _parse_metadata(lines, start, end)
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

        postings = _parse_postings(lines, start, end)
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

    known_accounts = set(list_known_accounts(accounts_dat))
    selected_ids = set(selected_candidate_ids)
    selected_candidates = [candidate for candidate in candidates if candidate["id"] in selected_ids]
    missing_ids = sorted(selected_ids - {candidate["id"] for candidate in selected_candidates})
    if missing_ids:
        raise ValueError("Some selected historical matches are no longer available.")

    invalid_accounts = sorted(
        {
            str(candidate.get("targetAccount", "")).strip()
            for candidate in selected_candidates
            if str(candidate.get("targetAccount", "")).strip() not in known_accounts
        }
    )
    if invalid_accounts:
        raise ValueError(f"Unknown account(s): {', '.join(invalid_accounts)}")

    warnings: list[dict] = []
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    updated_count = 0

    for candidate in selected_candidates:
        idx = int(candidate["lineNo"]) - 1
        if idx < 0 or idx >= len(lines):
            warnings.append(
                {
                    "candidateId": candidate["id"],
                    "warning": f"Line {candidate['lineNo']} is no longer available.",
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
                        "warning": f"Line {candidate['lineNo']} changed after the scan and was skipped.",
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
                        "warning": f"Line {candidate['lineNo']} changed after the scan and was skipped.",
                    }
                )
                continue
            lines[idx] = f"{match.group(1)}{candidate['targetAccount']}"
            updated_count += 1
            continue

        warnings.append(
            {
                "candidateId": candidate["id"],
                "warning": f"Line {candidate['lineNo']} is no longer a posting.",
            }
        )

    if updated_count > 0:
        journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return updated_count, warnings
