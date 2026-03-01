from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


RULES_FILE = "20-match-rules.ndjson"


def rules_path(rules_dir: Path) -> Path:
    return rules_dir / RULES_FILE


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _parse_legacy_payee_rules(accounts_dat: Path) -> list[dict]:
    if not accounts_dat.exists():
        return []

    mapping: dict[str, tuple[str, str]] = {}
    current_account: str | None = None
    for raw in accounts_dat.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("account "):
            current_account = line[len("account "):].strip()
            continue
        if current_account and line.strip().startswith("payee "):
            payee = line.strip()[len("payee "):].strip()
            if payee:
                mapping[payee.lower()] = (payee, current_account)

    out: list[dict] = []
    now = _now_iso()
    for idx, (_, (payee, account)) in enumerate(sorted(mapping.items()), start=1):
        out.append(
            {
                "id": uuid4().hex[:12],
                "type": "payee",
                "pattern": payee,
                "account": account,
                "enabled": True,
                "position": idx,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    return out


def _normalize_rules(rules: list[dict]) -> list[dict]:
    ordered = sorted(rules, key=lambda r: (int(r.get("position", 0)), str(r.get("id", ""))))
    now = _now_iso()
    normalized: list[dict] = []
    for idx, rule in enumerate(ordered, start=1):
        normalized.append(
            {
                "id": str(rule.get("id") or uuid4().hex[:12]),
                "type": "payee",
                "pattern": str(rule.get("pattern", "")).strip(),
                "account": str(rule.get("account", "")).strip(),
                "enabled": bool(rule.get("enabled", True)),
                "position": idx,
                "createdAt": str(rule.get("createdAt") or now),
                "updatedAt": str(rule.get("updatedAt") or now),
            }
        )
    return [r for r in normalized if r["pattern"] and r["account"]]


def save_rules(path: Path, rules: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_rules(rules)
    lines = [json.dumps(rule, ensure_ascii=True, separators=(",", ":")) for rule in normalized]
    text = "\n".join(lines)
    if lines:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def load_rules(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rules: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        rules.append(json.loads(line))
    return _normalize_rules(rules)


def ensure_rules_store(rules_dir: Path, accounts_dat: Path) -> Path:
    path = rules_path(rules_dir)
    if path.exists():
        return path
    save_rules(path, _parse_legacy_payee_rules(accounts_dat))
    return path


def find_matching_rule(payee: str, rules: list[dict]) -> dict | None:
    key = payee.strip().lower()
    if not key:
        return None
    for rule in _normalize_rules(rules):
        if not rule["enabled"]:
            continue
        if key == rule["pattern"].strip().lower():
            return rule
    return None


def upsert_payee_rule(path: Path, payee: str, account: str) -> tuple[dict, bool]:
    payee_clean = payee.strip()
    if not payee_clean:
        raise ValueError("Payee is required")
    account_clean = account.strip()
    if not account_clean:
        raise ValueError("Account is required")

    rules = load_rules(path)
    key = payee_clean.lower()
    now = _now_iso()
    for rule in rules:
        if rule["type"] == "payee" and rule["pattern"].strip().lower() == key:
            changed = rule["account"] != account_clean
            rule["account"] = account_clean
            rule["enabled"] = True
            rule["updatedAt"] = now
            save_rules(path, rules)
            return rule, changed

    created = {
        "id": uuid4().hex[:12],
        "type": "payee",
        "pattern": payee_clean,
        "account": account_clean,
        "enabled": True,
        "position": len(rules) + 1,
        "createdAt": now,
        "updatedAt": now,
    }
    rules.append(created)
    save_rules(path, rules)
    return created, True


def reorder_rules(path: Path, ordered_ids: list[str]) -> list[dict]:
    rules = load_rules(path)
    by_id = {r["id"]: r for r in rules}
    missing = [rid for rid in ordered_ids if rid not in by_id]
    if missing:
        raise ValueError(f"Unknown rule ids: {', '.join(missing)}")

    rest = [r for r in rules if r["id"] not in ordered_ids]
    reordered = [by_id[rid] for rid in ordered_ids] + rest
    for idx, rule in enumerate(reordered, start=1):
        rule["position"] = idx
    save_rules(path, reordered)
    return load_rules(path)


def update_rule(
    path: Path,
    rule_id: str,
    *,
    pattern: str | None = None,
    account: str | None = None,
    enabled: bool | None = None,
) -> dict:
    rules = load_rules(path)
    now = _now_iso()
    for rule in rules:
        if rule["id"] != rule_id:
            continue
        if pattern is not None:
            pattern_clean = pattern.strip()
            if not pattern_clean:
                raise ValueError("Pattern is required")
            rule["pattern"] = pattern_clean
        if account is not None:
            account_clean = account.strip()
            if not account_clean:
                raise ValueError("Account is required")
            rule["account"] = account_clean
        if enabled is not None:
            rule["enabled"] = enabled
        rule["updatedAt"] = now
        save_rules(path, rules)
        return rule
    raise ValueError("Rule not found")


def delete_rule(path: Path, rule_id: str) -> bool:
    rules = load_rules(path)
    kept = [r for r in rules if r["id"] != rule_id]
    if len(kept) == len(rules):
        return False
    save_rules(path, kept)
    return True
