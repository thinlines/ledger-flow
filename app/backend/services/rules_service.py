from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


RULES_FILE = "20-match-rules.ndjson"
ALLOWED_FIELDS = {"payee"}
ALLOWED_OPERATORS = {"exact", "contains"}
ALLOWED_JOINERS = {"and", "or"}
ALLOWED_ACTION_TYPES = {"set_account", "add_tag", "set_kv", "append_comment"}


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
                "type": "match",
                "conditions": [{"field": "payee", "operator": "exact", "value": payee}],
                "account": account,
                "enabled": True,
                "position": idx,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    return out


def _normalize_conditions(raw_conditions: list[dict] | None, pattern: str | None = None) -> list[dict]:
    if raw_conditions is None:
        fallback = (pattern or "").strip()
        if not fallback:
            return []
        return [{"field": "payee", "operator": "exact", "value": fallback}]

    normalized: list[dict] = []
    for c in raw_conditions:
        field = str(c.get("field", "")).strip().lower()
        operator = str(c.get("operator", "")).strip().lower()
        value = str(c.get("value", "")).strip()
        joiner = str(c.get("joiner", "and")).strip().lower()
        if field not in ALLOWED_FIELDS or operator not in ALLOWED_OPERATORS or not value:
            continue
        if joiner not in ALLOWED_JOINERS:
            joiner = "and"
        normalized.append(
            {
                "field": field,
                "operator": operator,
                "value": value,
                "joiner": "and" if not normalized else joiner,
            }
        )
    return normalized


def _normalized_account_action(account: str) -> dict | None:
    account_clean = account.strip()
    if not account_clean:
        return None
    return {"type": "set_account", "account": account_clean}


def _normalize_actions(raw_actions: list[dict] | None, account: str | None = None) -> list[dict]:
    normalized: list[dict] = []
    for action in raw_actions or []:
        action_type = str(action.get("type", "")).strip().lower()
        if action_type not in ALLOWED_ACTION_TYPES:
            continue
        if action_type == "set_account":
            account_action = _normalized_account_action(str(action.get("account", "")))
            if account_action:
                normalized.append(account_action)
            continue
        if action_type == "add_tag":
            tag = str(action.get("tag", "")).strip()
            if tag:
                normalized.append({"type": "add_tag", "tag": tag})
            continue
        if action_type == "set_kv":
            key = str(action.get("key", "")).strip()
            value = str(action.get("value", "")).strip()
            if key and value:
                normalized.append({"type": "set_kv", "key": key, "value": value})
            continue
        if action_type == "append_comment":
            text = str(action.get("text", "")).strip()
            if text:
                normalized.append({"type": "append_comment", "text": text})

    if account is not None:
        account_action = _normalized_account_action(account)
        if account_action:
            replaced = False
            for idx, existing in enumerate(normalized):
                if existing["type"] == "set_account":
                    normalized[idx] = account_action
                    replaced = True
                    break
            if not replaced:
                normalized.insert(0, account_action)
    return normalized


def _extract_account(actions: list[dict]) -> str:
    for action in actions:
        if action.get("type") == "set_account":
            return str(action.get("account", "")).strip()
    return ""


def _normalize_rules(rules: list[dict]) -> list[dict]:
    ordered = sorted(rules, key=lambda r: (int(r.get("position", 0)), str(r.get("id", ""))))
    now = _now_iso()
    normalized: list[dict] = []
    for idx, rule in enumerate(ordered, start=1):
        normalized.append(
            {
                "id": str(rule.get("id") or uuid4().hex[:12]),
                "type": "match",
                "conditions": _normalize_conditions(rule.get("conditions"), pattern=rule.get("pattern")),
                "actions": _normalize_actions(rule.get("actions"), account=str(rule.get("account", "") or "")),
                "enabled": bool(rule.get("enabled", True)),
                "position": idx,
                "createdAt": str(rule.get("createdAt") or now),
                "updatedAt": str(rule.get("updatedAt") or now),
            }
        )
    return [r for r in normalized if r["conditions"] and r["actions"]]


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


def _matches_condition(condition: dict, context: dict[str, str]) -> bool:
    field = condition["field"]
    operator = condition["operator"]
    expected = condition["value"].strip().lower()
    actual = context.get(field, "").strip().lower()

    if operator == "exact":
        return actual == expected
    if operator == "contains":
        return expected in actual
    return False


def find_matching_rule(context: dict[str, str], rules: list[dict]) -> dict | None:
    for rule in _normalize_rules(rules):
        if not rule["enabled"]:
            continue
        matched = False
        for idx, condition in enumerate(rule["conditions"]):
            condition_match = _matches_condition(condition, context)
            if idx == 0:
                matched = condition_match
                continue
            if condition["joiner"] == "or":
                matched = matched or condition_match
            else:
                matched = matched and condition_match
        if matched:
            return rule
    return None


def extract_set_account(rule: dict) -> str | None:
    account = _extract_account(rule.get("actions", []))
    return account or None


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
        if (
            len(rule["conditions"]) == 1
            and rule["conditions"][0]["field"] == "payee"
            and rule["conditions"][0]["operator"] == "exact"
            and rule["conditions"][0]["value"].strip().lower() == key
        ):
            changed = extract_set_account(rule) != account_clean
            rule["actions"] = _normalize_actions(rule.get("actions"), account=account_clean)
            rule["enabled"] = True
            rule["updatedAt"] = now
            save_rules(path, rules)
            return rule, changed

    created = {
        "id": uuid4().hex[:12],
        "type": "match",
        "conditions": [{"field": "payee", "operator": "exact", "value": payee_clean}],
        "actions": [{"type": "set_account", "account": account_clean}],
        "enabled": True,
        "position": len(rules) + 1,
        "createdAt": now,
        "updatedAt": now,
    }
    rules.append(created)
    save_rules(path, rules)
    return created, True


def create_rule(
    path: Path,
    conditions: list[dict],
    *,
    actions: list[dict] | None = None,
    enabled: bool = True,
) -> dict:
    normalized_conditions = _normalize_conditions(conditions)
    if not normalized_conditions:
        raise ValueError("At least one valid condition is required")
    normalized_actions = _normalize_actions(actions)
    if not normalized_actions:
        raise ValueError("At least one valid action is required")

    rules = load_rules(path)
    now = _now_iso()
    created = {
        "id": uuid4().hex[:12],
        "type": "match",
        "conditions": normalized_conditions,
        "actions": normalized_actions,
        "enabled": enabled,
        "position": len(rules) + 1,
        "createdAt": now,
        "updatedAt": now,
    }
    rules.append(created)
    save_rules(path, rules)
    return created


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
    conditions: list[dict] | None = None,
    actions: list[dict] | None = None,
    enabled: bool | None = None,
) -> dict:
    rules = load_rules(path)
    now = _now_iso()
    for rule in rules:
        if rule["id"] != rule_id:
            continue
        if conditions is not None:
            normalized_conditions = _normalize_conditions(conditions)
            if not normalized_conditions:
                raise ValueError("At least one valid condition is required")
            rule["conditions"] = normalized_conditions
        if actions is not None:
            normalized_actions = _normalize_actions(actions)
            if not normalized_actions:
                raise ValueError("At least one valid action is required")
            rule["actions"] = normalized_actions
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
