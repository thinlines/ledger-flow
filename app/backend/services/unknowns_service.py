from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

ACCOUNT_LINE_RE = re.compile(r"^(\s+)([^\s].*?)(\s{2,}|\t+)(.*)$")
HEADER_RE = re.compile(r"^(\d{4}[-/]\d{2}[-/]\d{2})(?:\s+[*!])?(?:\s+\([^)]+\))?\s*(.*)$")
TXN_START_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}")


def _load_known_accounts(accounts_dat: Path) -> set[str]:
    known = set()
    for line in accounts_dat.read_text(encoding="utf-8").splitlines():
        if line.startswith("account "):
            known.add(line[len("account "):].strip())
    return known


def _load_payee_rules(accounts_dat: Path) -> dict[str, str]:
    current_account = None
    mapping = {}
    for raw in accounts_dat.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("account "):
            current_account = line[len("account "):].strip()
            continue
        if current_account and line.strip().startswith("payee "):
            payee = line.strip()[len("payee "):].strip()
            mapping[payee.lower()] = current_account
    return mapping


def scan_unknowns(journal_path: Path, accounts_dat: Path) -> dict:
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    payee_rules = _load_payee_rules(accounts_dat)
    grouped: dict[str, dict] = defaultdict(lambda: {"txns": []})

    current_payee = ""
    current_date = ""
    for i, line in enumerate(lines):
        if TXN_START_RE.match(line):
            m = HEADER_RE.match(line)
            if m:
                current_date = m.group(1)
                current_payee = m.group(2).strip() or "(no payee)"
            else:
                current_payee = "(no payee)"
                current_date = ""
            continue

        if "Unknown" not in line:
            continue

        am = ACCOUNT_LINE_RE.match(line)
        if not am:
            continue
        account = am.group(2).strip()
        if "Unknown" not in account:
            continue

        key = current_payee.lower()
        group = grouped[key]
        group["groupKey"] = key
        group["payeeDisplay"] = current_payee
        group["suggestedAccount"] = payee_rules.get(key)
        group["txns"].append(
            {
                "txnId": f"{journal_path.name}:{i+1}",
                "date": current_date,
                "lineNo": i + 1,
                "currentAccount": account,
                "line": line,
            }
        )

    return {"groups": list(grouped.values())}


def apply_unknown_mappings(
    journal_path: Path,
    accounts_dat: Path,
    mappings: dict[str, str],
    scanned_groups: list[dict],
) -> tuple[int, int, list[dict]]:
    known_accounts = _load_known_accounts(accounts_dat)
    warnings: list[dict] = []

    lines = journal_path.read_text(encoding="utf-8").splitlines()
    txn_updates = 0
    for group in scanned_groups:
        key = group["groupKey"]
        chosen = mappings.get(key)
        if not chosen:
            continue
        if chosen not in known_accounts:
            warnings.append({"groupKey": key, "warning": f"Unknown account: {chosen}"})

        for txn in group["txns"]:
            idx = txn["lineNo"] - 1
            if idx < 0 or idx >= len(lines):
                continue
            m = ACCOUNT_LINE_RE.match(lines[idx])
            if not m:
                continue
            if "Unknown" not in m.group(2):
                continue
            lines[idx] = f"{m.group(1)}{chosen}{m.group(3)}{m.group(4)}"
            txn_updates += 1

    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rules_text = accounts_dat.read_text(encoding="utf-8")
    rules_lines = rules_text.splitlines()
    existing_payee_to_account = _load_payee_rules(accounts_dat)
    rule_adds = 0

    for group in scanned_groups:
        key = group["groupKey"]
        payee = group["payeeDisplay"]
        chosen = mappings.get(key)
        if not chosen:
            continue

        existing = existing_payee_to_account.get(key)
        if existing == chosen:
            continue
        if existing and existing != chosen:
            warnings.append(
                {
                    "groupKey": key,
                    "warning": f"Payee already mapped to {existing}; skipped adding conflicting rule for {chosen}",
                }
            )
            continue

        insert_at = None
        for i, line in enumerate(rules_lines):
            if line.startswith("account ") and line[len("account "):].strip() == chosen:
                insert_at = i + 1
                while insert_at < len(rules_lines) and not rules_lines[insert_at].startswith("account "):
                    insert_at += 1
                break

        if insert_at is None:
            warnings.append({"groupKey": key, "warning": f"Target account block not found: {chosen}"})
            continue

        rule_line = f"\tpayee {payee}"
        rules_lines.insert(insert_at, rule_line)
        existing_payee_to_account[key] = chosen
        rule_adds += 1

    accounts_dat.write_text("\n".join(rules_lines) + "\n", encoding="utf-8")
    return txn_updates, rule_adds, warnings
