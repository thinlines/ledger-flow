from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
HEADER_RE = re.compile(r"^(\d{4}[-/]\d{2}[-/]\d{2})(?:\s+[*!])?(?:\s+\([^)]+\))?\s*(.*)$")
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")


def list_known_accounts(accounts_dat: Path) -> list[str]:
    return sorted(_load_known_accounts(accounts_dat))


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
        if not m:
            continue
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
    return postings


def scan_unknowns(journal_path: Path, accounts_dat: Path) -> dict:
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    payee_rules = _load_payee_rules(accounts_dat)
    grouped: dict[str, dict] = defaultdict(lambda: {"txns": []})

    for start, end in _iter_transaction_ranges(lines):
        header_line = lines[start]
        hm = HEADER_RE.match(header_line)
        if hm:
            current_date = hm.group(1)
            current_payee = hm.group(2).strip() or "(no payee)"
        else:
            current_date = ""
            current_payee = "(no payee)"

        postings = _parse_postings(lines, start, end)
        unknown_postings = [p for p in postings if "Unknown" in p["account"]]
        if not unknown_postings:
            continue

        counterparty = ""
        for p in postings:
            if "Unknown" not in p["account"]:
                counterparty = p["account"]
                break

        key = current_payee.lower()
        group = grouped[key]
        group["groupKey"] = key
        group["payeeDisplay"] = current_payee
        group["suggestedAccount"] = payee_rules.get(key)

        for p in unknown_postings:
            group["txns"].append(
                {
                    "txnId": f"{journal_path.name}:{p['lineNo']}",
                    "date": current_date,
                    "lineNo": p["lineNo"],
                    "currentAccount": p["account"],
                    "amount": p["amount"],
                    "counterpartyAccount": counterparty,
                    "line": p["line"],
                }
            )

    return {"groups": list(grouped.values())}


def apply_unknown_mappings(
    journal_path: Path,
    accounts_dat: Path,
    mappings: dict[str, str],
    scanned_groups: list[dict],
) -> tuple[int, list[dict]]:
    known_accounts = _load_known_accounts(accounts_dat)
    invalid = sorted({acct for acct in mappings.values() if acct and acct not in known_accounts})
    if invalid:
        raise ValueError(f"Unknown account(s): {', '.join(invalid)}")

    warnings: list[dict] = []
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    txn_updates = 0

    for group in scanned_groups:
        key = group["groupKey"]
        chosen = mappings.get(key)
        if not chosen:
            continue

        for txn in group["txns"]:
            idx = txn["lineNo"] - 1
            if idx < 0 or idx >= len(lines):
                continue
            m = ACCOUNT_LINE_RE.match(lines[idx])
            if not m:
                warnings.append({"groupKey": key, "warning": f"Line {txn['lineNo']} is no longer a posting"})
                continue
            if "Unknown" not in m.group(2):
                warnings.append({"groupKey": key, "warning": f"Line {txn['lineNo']} is already resolved"})
                continue
            lines[idx] = f"{m.group(1)}{chosen}{m.group(3)}{m.group(4)}"
            txn_updates += 1

    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return txn_updates, warnings


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

    if existing.get(key) == account:
        return False, None
    if key in existing and existing[key] != account:
        return False, f"Payee already mapped to {existing[key]}"

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
