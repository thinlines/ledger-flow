from __future__ import annotations

from datetime import UTC, date as calendar_date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from .config_service import AppConfig
from .operations_service import record_operation
from .projection_db import connect, ensure_database


ALLOWED_FIELDS = {"payee", "merchant", "date", "amount", "account"}
FIELD_OPERATORS = {
    "payee": {"exact", "contains"},
    "merchant": {"exact", "contains"},
    "date": {"on_or_after", "before", "between"},
    "amount": {
        "exact",
        "less_than",
        "less_than_or_equal",
        "greater_than",
        "greater_than_or_equal",
        "between",
    },
    "account": {"exact", "contains"},
}
AMOUNT_OPERATOR_ALIASES = {
    "eq": "exact",
    "equals": "exact",
    "lt": "less_than",
    "lte": "less_than_or_equal",
    "gt": "greater_than",
    "gte": "greater_than_or_equal",
}
ALLOWED_JOINERS = {"and", "or"}
ALLOWED_ACTION_TYPES = {"set_account", "add_tag", "set_kv", "append_comment"}
NANO_UNITS = Decimal("1000000000")


def _rules_dir(path: Path) -> Path:
    return path if path.is_dir() else path.parent


def _config_from_rules_dir(rules_dir: Path) -> AppConfig:
    root = rules_dir.parent
    return AppConfig(
        root_dir=root,
        config_toml=root / "settings" / "workspace.toml",
        workspace={"name": "Workspace", "start_year": 2026},
        dirs={
            "csv_dir": "inbox",
            "journal_dir": "journals",
            "init_dir": rules_dir.name,
            "opening_bal_dir": "opening",
            "imports_dir": "imports",
        },
        institution_templates={},
        import_accounts={},
        tracked_accounts={},
    )


def _db_path_for(path: Path) -> Path:
    return ensure_database(_config_from_rules_dir(_rules_dir(path)))


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _suggest_rule_name(conditions: list[dict]) -> str:
    if not conditions:
        return ""

    first = conditions[0]
    value = str(first.get("value", "")).strip()
    if not value:
        return ""

    if first.get("field") == "payee":
        if first.get("operator") == "exact":
            base = value
        elif first.get("operator") == "contains":
            base = f'Contains "{value}"'
        else:
            base = value
    elif first.get("field") == "date":
        if first.get("operator") == "on_or_after":
            base = f"On or after {value}"
        elif first.get("operator") == "before":
            base = f"Before {value}"
        elif first.get("operator") == "between":
            end_value = str(first.get("secondaryValue", "")).strip()
            base = f"{value} to {end_value}" if end_value else value
        else:
            base = value
    else:
        base = value

    extra_count = len(conditions) - 1
    if extra_count > 0:
        base = f"{base} +{extra_count}"
    return base


def _normalize_rule_name(name: str | None, conditions: list[dict], position: int | None = None) -> str:
    cleaned = (name or "").strip()
    if cleaned:
        return cleaned

    suggested = _suggest_rule_name(conditions)
    if suggested:
        return suggested

    if position is not None:
        return f"Rule {position}"
    return "Untitled rule"


def _normalize_date_value(value: str) -> str | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return calendar_date.fromisoformat(cleaned.replace("/", "-")).isoformat()
    except ValueError:
        return None


def _normalize_operator(field: str, operator: str) -> str:
    if field == "amount":
        return AMOUNT_OPERATOR_ALIASES.get(operator, operator)
    return operator


def _amount_to_nano(value: str) -> int | None:
    cleaned = str(value or "").strip().replace(",", "")
    if not cleaned:
        return None
    if cleaned.startswith("$"):
        cleaned = cleaned[1:].strip()
    parts = cleaned.split()
    if len(parts) == 2:
        if parts[0].isalpha():
            cleaned = parts[1]
        elif parts[1].isalpha():
            cleaned = parts[0]
    if cleaned.startswith("$"):
        cleaned = cleaned[1:].strip()
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    nano = amount * NANO_UNITS
    if nano != nano.to_integral_value():
        return None
    return int(nano)


def _normalize_conditions(raw_conditions: list[dict] | None, pattern: str | None = None) -> list[dict]:
    if raw_conditions is None:
        fallback = (pattern or "").strip()
        if not fallback:
            return []
        return [{"field": "payee", "operator": "exact", "value": fallback}]

    normalized: list[dict] = []
    for c in raw_conditions:
        field = str(c.get("field", "")).strip().lower()
        operator = _normalize_operator(field, str(c.get("operator", "")).strip().lower())
        value = str(c.get("value", "")).strip()
        secondary_value = str(c.get("secondaryValue", "")).strip()
        joiner = str(c.get("joiner", "and")).strip().lower()
        if field not in ALLOWED_FIELDS or operator not in FIELD_OPERATORS.get(field, set()):
            continue

        normalized_value = value
        normalized_secondary_value = None
        if field == "date":
            normalized_value = _normalize_date_value(value) or ""
            if operator == "between":
                normalized_secondary_value = _normalize_date_value(secondary_value)
                if (
                    not normalized_value
                    or not normalized_secondary_value
                ):
                    continue
                if normalized_value > normalized_secondary_value:
                    normalized_value, normalized_secondary_value = (
                        normalized_secondary_value,
                        normalized_value,
                    )
            elif not normalized_value:
                continue
        elif field == "amount":
            normalized_amount = _amount_to_nano(value)
            if normalized_amount is None:
                continue
            if operator == "between":
                normalized_secondary_amount = _amount_to_nano(secondary_value)
                if normalized_secondary_amount is None:
                    continue
                if normalized_amount > normalized_secondary_amount:
                    value, secondary_value = secondary_value, value
                normalized_secondary_value = secondary_value
        elif not value:
            continue

        if joiner not in ALLOWED_JOINERS:
            joiner = "and"
        item = {
            "field": field,
            "operator": operator,
            "value": normalized_value,
            "joiner": "and" if not normalized else joiner,
        }
        if normalized_secondary_value:
            item["secondaryValue"] = normalized_secondary_value
        normalized.append(item)
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
        conditions = _normalize_conditions(rule.get("conditions"), pattern=rule.get("pattern"))
        actions = _normalize_actions(rule.get("actions"), account=str(rule.get("account", "") or ""))
        normalized.append(
            {
                "id": str(rule.get("id") or uuid4().hex[:12]),
                "type": "match",
                "name": _normalize_rule_name(rule.get("name"), conditions, idx),
                "conditions": conditions,
                "actions": actions,
                "enabled": bool(rule.get("enabled", True)),
                "position": idx,
                "createdAt": str(rule.get("createdAt") or now),
                "updatedAt": str(rule.get("updatedAt") or now),
            }
        )
    return [r for r in normalized if r["conditions"] and r["actions"]]


def _condition_groups(conditions: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    for condition in conditions:
        if current and condition.get("joiner") == "or":
            groups.append(current)
            current = []
        current.append(condition)
    if current:
        groups.append(current)
    return groups


def _action_storage(action: dict) -> tuple[str, str | None, str]:
    action_type = action["type"]
    if action_type == "set_account":
        return action_type, None, str(action.get("account", ""))
    if action_type == "add_tag":
        return action_type, None, str(action.get("tag", ""))
    if action_type == "set_kv":
        return action_type, str(action.get("key", "")), str(action.get("value", ""))
    if action_type == "append_comment":
        return action_type, None, str(action.get("text", ""))
    return action_type, None, ""


def _action_from_storage(action_type: str, key: str | None, value: str) -> dict:
    if action_type == "set_account":
        return {"type": "set_account", "account": value}
    if action_type == "add_tag":
        return {"type": "add_tag", "tag": value}
    if action_type == "set_kv":
        return {"type": "set_kv", "key": key or "", "value": value}
    if action_type == "append_comment":
        return {"type": "append_comment", "text": value}
    return {"type": action_type, "value": value}


def _replace_rules_in_db(path: Path, rules: list[dict]) -> None:
    db_path = _db_path_for(path)
    with connect(db_path) as conn:
        conn.execute("DELETE FROM rules")
        for rule in _normalize_rules(rules):
            conn.execute(
                """
                INSERT INTO rules (id, type, name, enabled, position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["id"],
                    rule["type"],
                    rule["name"],
                    1 if rule["enabled"] else 0,
                    rule["position"],
                    rule["createdAt"],
                    rule["updatedAt"],
                ),
            )
            for group_order, group in enumerate(_condition_groups(rule["conditions"]), start=1):
                group_id = uuid4().hex
                conn.execute(
                    """
                    INSERT INTO rule_condition_groups (id, rule_id, group_order)
                    VALUES (?, ?, ?)
                    """,
                    (group_id, rule["id"], group_order),
                )
                for condition_order, condition in enumerate(group, start=1):
                    conn.execute(
                        """
                        INSERT INTO rule_conditions (
                            id, group_id, condition_order, field, operator, value, secondary_value
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            uuid4().hex,
                            group_id,
                            condition_order,
                            condition["field"],
                            condition["operator"],
                            condition["value"],
                            condition.get("secondaryValue"),
                        ),
                    )
            for action_order, action in enumerate(rule["actions"], start=1):
                action_type, key, value = _action_storage(action)
                conn.execute(
                    """
                    INSERT INTO rule_actions (id, rule_id, action_order, action_type, key, value)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (uuid4().hex, rule["id"], action_order, action_type, key, value),
                )


def _load_rules_from_db(path: Path) -> list[dict]:
    db_path = _db_path_for(path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, type, name, enabled, position, created_at, updated_at
            FROM rules
            ORDER BY position, id
            """
        ).fetchall()
        rules: list[dict] = []
        for rule_id, rule_type, name, enabled, position, created_at, updated_at in rows:
            condition_rows = conn.execute(
                """
                SELECT g.group_order, c.condition_order, c.field, c.operator, c.value, c.secondary_value
                FROM rule_condition_groups g
                JOIN rule_conditions c ON c.group_id = g.id
                WHERE g.rule_id = ?
                ORDER BY g.group_order, c.condition_order
                """,
                (rule_id,),
            ).fetchall()
            conditions: list[dict] = []
            previous_group: int | None = None
            for group_order, condition_order, field, operator, value, secondary_value in condition_rows:
                condition = {
                    "field": field,
                    "operator": operator,
                    "value": value,
                    "joiner": "or" if previous_group is not None and group_order != previous_group else "and",
                }
                if secondary_value:
                    condition["secondaryValue"] = secondary_value
                conditions.append(condition)
                previous_group = group_order

            action_rows = conn.execute(
                """
                SELECT action_type, key, value
                FROM rule_actions
                WHERE rule_id = ?
                ORDER BY action_order
                """,
                (rule_id,),
            ).fetchall()
            actions = [_action_from_storage(action_type, key, value) for action_type, key, value in action_rows]
            rules.append(
                {
                    "id": rule_id,
                    "type": rule_type,
                    "name": name,
                    "conditions": conditions,
                    "actions": actions,
                    "enabled": bool(enabled),
                    "position": position,
                    "createdAt": created_at,
                    "updatedAt": updated_at,
                }
            )
    return _normalize_rules(rules)


def _record_rule_operation(path: Path, operation_type: str, summary: str, payload: dict) -> None:
    config = _config_from_rules_dir(_rules_dir(path))
    record_operation(
        config,
        operation_type=operation_type,
        summary=summary,
        payload=payload,
        files=[],
        entities=[
            {
                "entity_type": "rule",
                "entity_id": str(payload.get("rule_id") or payload.get("id") or ""),
                "role": "affected",
                "payload": payload,
            }
        ],
        undo_mode="unavailable",
    )


def save_rules(path: Path, rules: list[dict]) -> None:
    _rules_dir(path).mkdir(parents=True, exist_ok=True)
    _replace_rules_in_db(path, rules)


def load_rules(path: Path) -> list[dict]:
    return _load_rules_from_db(path)


def ensure_rules_store(rules_dir: Path) -> Path:
    rules_dir.mkdir(parents=True, exist_ok=True)
    _db_path_for(rules_dir)
    return rules_dir


def _context_values(context: dict, field: str) -> list[str]:
    candidates = []
    plural = f"{field}s"
    if field in context:
        candidates.append(context.get(field))
    if plural in context:
        candidates.append(context.get(plural))

    out: list[str] = []
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, (list, tuple, set)):
            out.extend(str(value).strip() for value in candidate if str(value).strip())
        else:
            value = str(candidate).strip()
            if value:
                out.append(value)
    return out


def _matches_text_condition(condition: dict, values: list[str]) -> bool:
    operator = condition["operator"]
    expected = condition["value"].strip().lower()
    actuals = [value.lower() for value in values]
    if operator == "exact":
        return any(actual == expected for actual in actuals)
    if operator == "contains":
        return any(expected in actual for actual in actuals)
    return False


def _matches_amount_condition(condition: dict, values: list[str]) -> bool:
    operator = condition["operator"]
    expected = _amount_to_nano(condition["value"])
    if expected is None:
        return False
    actuals = [nano for value in values if (nano := _amount_to_nano(value)) is not None]
    if not actuals:
        return False
    if operator == "exact":
        return any(actual == expected for actual in actuals)
    if operator == "less_than":
        return any(actual < expected for actual in actuals)
    if operator == "less_than_or_equal":
        return any(actual <= expected for actual in actuals)
    if operator == "greater_than":
        return any(actual > expected for actual in actuals)
    if operator == "greater_than_or_equal":
        return any(actual >= expected for actual in actuals)
    if operator == "between":
        secondary = _amount_to_nano(str(condition.get("secondaryValue", "")))
        if secondary is None:
            return False
        low, high = sorted((expected, secondary))
        return any(low <= actual <= high for actual in actuals)
    return False


def _matches_condition(condition: dict, context: dict) -> bool:
    field = condition["field"]
    operator = condition["operator"]
    expected = condition["value"].strip()

    if field in {"payee", "merchant", "account"}:
        return _matches_text_condition(condition, _context_values(context, field))

    if field == "date":
        actual = str(context.get(field, "")).strip()
        actual_date = _normalize_date_value(actual)
        expected_date = _normalize_date_value(expected)
        if not actual_date or not expected_date:
            return False
        if operator == "on_or_after":
            return actual_date >= expected_date
        if operator == "before":
            return actual_date < expected_date
        if operator == "between":
            secondary_value = _normalize_date_value(str(condition.get("secondaryValue", "")))
            if not secondary_value:
                return False
            return expected_date <= actual_date <= secondary_value
    if field == "amount":
        return _matches_amount_condition(condition, _context_values(context, field))
    return False


def find_matching_rule(context: dict, rules: list[dict]) -> dict | None:
    for rule in _normalize_rules(rules):
        if not rule["enabled"]:
            continue
        if any(
            all(_matches_condition(condition, context) for condition in group)
            for group in _condition_groups(rule["conditions"])
        ):
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
            if changed:
                _record_rule_operation(
                    path,
                    "rule.updated.v1",
                    f"Updated rule: {rule['name']}",
                    {"rule_id": rule["id"], "rule": rule},
                )
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
    _record_rule_operation(
        path,
        "rule.created.v1",
        f"Created rule: {_normalize_rule_name(None, created['conditions'])}",
        {"rule_id": created["id"], "rule": _normalize_rules([created])[0]},
    )
    return created, True


def create_rule(
    path: Path,
    conditions: list[dict],
    *,
    name: str | None = None,
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
        "name": _normalize_rule_name(name, normalized_conditions, len(rules) + 1),
        "conditions": normalized_conditions,
        "actions": normalized_actions,
        "enabled": enabled,
        "position": len(rules) + 1,
        "createdAt": now,
        "updatedAt": now,
    }
    rules.append(created)
    save_rules(path, rules)
    _record_rule_operation(
        path,
        "rule.created.v1",
        f"Created rule: {created['name']}",
        {"rule_id": created["id"], "rule": created},
    )
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
    _record_rule_operation(
        path,
        "rule.reordered.v1",
        "Reordered rules",
        {"ordered_ids": ordered_ids},
    )
    return load_rules(path)


def update_rule(
    path: Path,
    rule_id: str,
    *,
    name: str | None = None,
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
        if name is not None:
            rule["name"] = _normalize_rule_name(name, rule["conditions"], int(rule.get("position", 0)) or None)
        if actions is not None:
            normalized_actions = _normalize_actions(actions)
            if not normalized_actions:
                raise ValueError("At least one valid action is required")
            rule["actions"] = normalized_actions
        if enabled is not None:
            rule["enabled"] = enabled
        rule["updatedAt"] = now
        save_rules(path, rules)
        _record_rule_operation(
            path,
            "rule.updated.v1",
            f"Updated rule: {rule['name']}",
            {"rule_id": rule["id"], "rule": rule},
        )
        return rule
    raise ValueError("Rule not found")


def delete_rule(path: Path, rule_id: str) -> bool:
    rules = load_rules(path)
    kept = [r for r in rules if r["id"] != rule_id]
    if len(kept) == len(rules):
        return False
    deleted = next(r for r in rules if r["id"] == rule_id)
    save_rules(path, kept)
    _record_rule_operation(
        path,
        "rule.deleted.v1",
        f"Deleted rule: {deleted['name']}",
        {"rule_id": rule_id, "rule": deleted},
    )
    return True
