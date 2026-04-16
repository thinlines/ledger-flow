# Task 06 — Derive `institution_registry` from the Adapter Registry

## Title

Replace `institution_registry.py`'s hand-maintained `_REGISTRY` dict with a function that constructs `InstitutionTemplate` entries from registered adapters. Schwab and Bank of Beijing stay hardcoded until Task 07.

## Objective

Turn `institution_registry.py` into generated state so adding a new institution in the future means writing an adapter — not editing two files. Consumers of the registry (`main.py`, `workspace_service.py`, `import_profile_service.py`) see identical behavior.

## Context

Today (`app/backend/services/institution_registry.py`), `_REGISTRY` is a dict of five hand-written `InstitutionTemplate` instances: `wells_fargo`, `charles_schwab`, `icbc`, `alipay`, `bank_of_beijing`. Three of those (WF, Alipay, ICBC) have adapters after Wave 3. Two (Schwab, BJB) have no adapter — they're going away in Task 07 per the 2026-04-15 scope trim.

After Wave 3 completes, the adapter is the natural single source of truth for an institution's parsing-relevant metadata (encoding, slicing, date format). The user-facing presentation metadata (display name, ledger-account prefix, aliases) has lived in `institution_registry.py` and can move onto the adapter class as class attributes. Once both live on the adapter, the registry becomes a thin aggregator over the adapter list plus two hardcoded bridge entries (Schwab, BJB) that Task 07 will delete.

## Scope

### Included

**Extend every adapter class from Tasks 02, 04, 05 with presentation metadata as class attributes:**

For `WellsFargoAdapter` (implementations/wells_fargo.py):

```python
display_name = "Wells Fargo"
csv_date_format = "%m/%d/%Y"
suggested_ledger_prefix = "Assets:Bank:Wells Fargo"
aliases = ("wfchk", "wfsav", "wfcc", "wells-fargo", "wellsfargo")
head = 0
tail = 0
encoding = "utf-8"
```

For `AlipayAdapter` (implementations/alipay.py):

```python
display_name = "Alipay"
csv_date_format = "%Y-%m-%d"
suggested_ledger_prefix = "Assets:Alipay"
aliases = ("alipay",)
head = 13
tail = 1
encoding = "GB18030"
```

For `IcbcAdapter` (implementations/icbc.py):

```python
display_name = "Industrial and Commercial Bank of China"
csv_date_format = "%Y-%m-%d"
suggested_ledger_prefix = "Assets:Bank:ICBC"
aliases = ("icbc",)
head = 7
tail = 2
encoding = "utf-8"
```

(Exact values cross-checked against today's `institution_registry.py:_REGISTRY` — no drift.)

**Rewrite `app/backend/services/institution_registry.py`:**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from .parsers import registry as parsers_registry


@dataclass(frozen=True)
class InstitutionTemplate:
    id: str
    display_name: str
    parser: str
    csv_date_format: str
    suggested_ledger_prefix: str
    aliases: tuple[str, ...] = ()
    head: int = 0
    tail: int = 0
    encoding: str = "utf-8"


# Schwab and BJB stay as hardcoded bridge entries until Task 07 deletes them.
# Both are out of scope for the CSV parser refactor (brokerage support deferred;
# BJB cut as YAGNI per 2026-04-15 scope trim). See memory
# project_csv_parser_refactor.md.
_LEGACY_BRIDGES: tuple[InstitutionTemplate, ...] = (
    InstitutionTemplate(
        id="charles_schwab",
        display_name="Charles Schwab",
        parser="schwab",
        csv_date_format="%m/%d/%Y",
        suggested_ledger_prefix="Assets:Investments:Schwab",
        aliases=("schwab",),
    ),
    InstitutionTemplate(
        id="bank_of_beijing",
        display_name="Bank of Beijing",
        parser="bjb",
        csv_date_format="%Y/%m/%d",
        suggested_ledger_prefix="Assets:Bank:BJB",
        aliases=("bjb", "beijing-bank", "bank-of-beijing"),
        head=1,
        tail=0,
    ),
)


def _build_registry() -> dict[str, InstitutionTemplate]:
    parsers_registry.discover()
    out: dict[str, InstitutionTemplate] = {b.id: b for b in _LEGACY_BRIDGES}
    for adapter in parsers_registry.list_adapters():
        if adapter.institution in out:
            raise RuntimeError(
                f"Institution slug collision: {adapter.institution!r} already "
                f"declared by a legacy bridge"
            )
        out[adapter.institution] = InstitutionTemplate(
            id=adapter.institution,
            display_name=adapter.display_name,
            parser=adapter.name,
            csv_date_format=adapter.csv_date_format,
            suggested_ledger_prefix=adapter.suggested_ledger_prefix,
            aliases=tuple(adapter.aliases),
            head=int(adapter.head),
            tail=int(adapter.tail),
            encoding=str(adapter.encoding),
        )
    return out


_REGISTRY = _build_registry()
_ALIAS_TO_ID = {
    alias.lower(): t.id
    for t in _REGISTRY.values()
    for alias in (t.id, *t.aliases)
}


def canonical_template_id(slug: str) -> str | None:
    return _ALIAS_TO_ID.get(slug.lower())


def display_name_for(template_id: str) -> str:
    return _REGISTRY[template_id].display_name


def get_template(template_id: str) -> InstitutionTemplate:
    return _REGISTRY[template_id]


def list_templates() -> Iterable[InstitutionTemplate]:
    return _REGISTRY.values()
```

**Verify all existing consumers still work:**

- `main.py`: uses `canonical_template_id`, `display_name_for`, `list_templates`.
- `workspace_service.py`: uses `get_template`.
- `import_profile_service.py`: uses `canonical_template_id`, `display_name_for`.

The new `institution_registry.py` preserves every public API: same function names, same return types, same dict keys. Consumer call sites compile and run without edit.

**New test `app/backend/tests/test_institution_registry_derivation.py`:**

- Assert `list_templates()` returns exactly 5 entries (3 derived + Schwab bridge + BJB bridge) and includes `wells_fargo`, `alipay`, `icbc`, `charles_schwab`, `bank_of_beijing`.
- Assert `canonical_template_id("wfchk")` returns `"wells_fargo"` (alias resolution via adapter attrs).
- Assert `canonical_template_id("schwab")` returns `"charles_schwab"` (Schwab bridge).
- Assert `canonical_template_id("bjb")` returns `"bank_of_beijing"` (BJB bridge).
- Assert `get_template("alipay").encoding == "GB18030"` and `.head == 13` (adapter-derived metadata).
- Assert collision detection: if an adapter declares `institution == "charles_schwab"` or `"bank_of_beijing"`, `_build_registry()` raises `RuntimeError`. Exercise via a throwaway adapter registered/unregistered inside a `try/finally`.

### Explicitly excluded

- No Schwab or BJB removal (that's Task 07).
- No changes to `csv_normalizer.py` — it still reads `config.institution_templates` (the user's workspace config), which is populated from `institution_registry.list_templates()` at setup time; the derivation change is transparent to it.
- No frontend, API, or config file changes.
- No changes to workspace bootstrap or account setup flows.
- No adapter behavior changes — only class-attribute additions.
- No deletion of the old hand-written `_REGISTRY` dict values; they're replaced by the generated version.

## System Behavior

**Inputs:** none at runtime — `_REGISTRY` is computed once at module load by iterating registered adapters + the legacy bridges.

**Logic:** `_build_registry()` seeds the dict with the two legacy bridge entries (Schwab, BJB), calls `parsers_registry.discover()`, then reads each adapter's class attributes to build `InstitutionTemplate` instances. Returns a dict keyed by `adapter.institution`.

**Outputs:** same public API as today — `canonical_template_id`, `display_name_for`, `get_template`, `list_templates`, and the module-level `_REGISTRY` / `_ALIAS_TO_ID` constants.

## System Invariants

- `list_templates()` returns identical `InstitutionTemplate` content (field-by-field) as today's hand-written `_REGISTRY`. Verified by `test_institution_registry_derivation.py` asserting specific field values for each institution.
- Schwab entry exists and is identical in content to today's `_REGISTRY["charles_schwab"]`.
- BJB entry exists and is identical in content to today's `_REGISTRY["bank_of_beijing"]`.
- Every consumer of `institution_registry` keeps working without source edit.
- `_build_registry()` is deterministic.
- Registration-level collisions are caught loudly (`RuntimeError`).

## States

Not applicable.

## Edge Cases

- **Adapter without required class attributes.** `InstitutionTemplate(...)` constructor fails with `AttributeError`. Surface loudly during module load.
- **Two adapters declaring the same `institution` slug.** `_build_registry()` raises `RuntimeError`.
- **Adapter claims `institution == "charles_schwab"` or `"bank_of_beijing"`.** Collision check raises — legacy bridges own those slugs through Task 07.
- **Alias collision across institutions.** If two institutions declare overlapping aliases, `_ALIAS_TO_ID` silently overwrites. Add a pre-flight check that raises on alias collision. Low probability, low cost to guard.
- **Schwab / BJB metadata drift.** The `_LEGACY_BRIDGES` tuple must stay identical in content to today's `_REGISTRY["charles_schwab"]` and `_REGISTRY["bank_of_beijing"]` until Task 07. Do not "improve" either during this task.
- **Consumer that iterates `_REGISTRY` directly.** Still works — `_REGISTRY` remains a module-level dict with the same shape.

## Failure Behavior

- **Import-time failure in an adapter module.** Breaks `parsers_registry.discover()`, breaks `_build_registry()`, breaks every registry consumer. Correct behavior.
- **Missing required class attribute on an adapter.** Import fails at module load with `AttributeError`.
- **Alias collision at startup.** `RuntimeError` with both institution slugs.

## Regression Risks

- **Consumer call-site drift.** `canonical_template_id`, `display_name_for`, `get_template`, `list_templates` must keep identical signatures and return shapes.
- **Adapter class-attribute typo.** Caught by `test_institution_registry_derivation.py` asserting specific field values.
- **`institution_registry` import cycle.** `institution_registry` now imports `services.parsers.registry`. Parsers' `registry.py` must not import from `institution_registry` — verify with grep. (Task 0 locked this.)
- **Workspace config staleness.** User workspaces may have `workspace/settings/workspace.toml` snapshots of `institution_templates`. The registry-derivation does not regenerate those snapshots; users' workspace configs stay as-is. Confirm that `workspace_service` does not re-read the registry to overwrite user config.
- **Order dependency.** `_build_registry()` calls `parsers_registry.discover()` explicitly, which triggers the `implementations/*.py` imports. Tested by the smoke-test for `list_templates()` count.
- **Test ordering contamination.** `_build_registry()` is a one-shot at module load; no test should re-invoke it without cleanup.

## Acceptance Criteria

- `uv run python -c "from app.backend.services import institution_registry; print(sorted(t.id for t in institution_registry.list_templates()))"` prints `['alipay', 'bank_of_beijing', 'charles_schwab', 'icbc', 'wells_fargo']`.
- `uv run python -c "from app.backend.services import institution_registry; t = institution_registry.get_template('alipay'); print(t.display_name, t.encoding, t.head, t.tail)"` prints `Alipay GB18030 13 1`.
- `uv run python -c "from app.backend.services import institution_registry; t = institution_registry.get_template('bank_of_beijing'); print(t.display_name, t.parser)"` prints `Bank of Beijing bjb`.
- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py app/backend/tests/test_institution_registry_derivation.py -q` green.
- `uv run pytest app/backend/tests/ -q --ignore=app/backend/tests/test_unknown_stage_resume.py --ignore=app/backend/tests/test_workspace_bootstrap.py` green.
- `grep -rE "InstitutionTemplate\(" app/backend/services/institution_registry.py | wc -l` shows exactly `2` (the Schwab and BJB hardcoded bridges).
- `grep -rE "from .parsers import|from app.backend.services.parsers" app/backend/services/institution_registry.py` shows the new import.
- `git diff --stat` shows: `institution_registry.py` rewritten; each of `implementations/wells_fargo.py`, `alipay.py`, `icbc.py` gains 7 class attributes; new test file added.

## Proposed Sequence

1. **Extend adapter class attributes.** Edit all three adapter files (one combined commit or one per adapter) to add the metadata attrs. Verify `uv run pytest test_csv_parser_fixtures.py -q` still green. Commit.
2. **Write `_build_registry()` logic** (either inline in `institution_registry.py` or in a small helper module — pick the path least likely to cycle-import). Commit.
3. **Rewrite `institution_registry.py`** to use `_build_registry()`. Keep public function signatures identical. Verify all consumers still import cleanly. Commit.
4. **Write `test_institution_registry_derivation.py`** with the assertions above. Commit.
5. **Run the full backend test suite** with the usual ignore set. Any new failure is a regression; fix or revert. Commit delivery notes.

## Definition of Done

- All Acceptance Criteria met.
- Every consumer of `institution_registry` compiles and passes tests without source edit.
- Adding a new bank in the future means writing one adapter file with 8+ class attributes — no `institution_registry.py` edit required.
- Schwab and BJB still work (both route through their legacy `BankCSV` subclasses via the Task 02 fallback).

## Dependencies

- **Task 01** (writer) — transitive through Wave 3.
- **Task 02** (dispatch seam) — transitive through Wave 3.
- **Tasks 04, 05** — both Wave 3 adapters must be registered. Task 06 reads them both at load time.
- **Blocks Task 07** — the Schwab and BJB bridge entries must exist before 07 can cleanly delete them.

## Out of Scope

- Schwab or BJB removal (Task 07).
- Deletion of `Scripts/BankCSV.py` (Task 07).
- Changes to workspace bootstrap defaults or user-visible account setup copy.
- Adding new institutions. This task proves the pattern; any new institution lands after Task 07.
