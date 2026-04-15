# Current Task

**Status: READY — drafted 2026-04-13**

## Title

Adapter/translator scaffolding and golden-fixture baselines for the CSV import refactor

## Objective

Establish the internal contract for the `services/parsers/` refactor (dataclasses, protocols, registry, discovery) and check in golden-fixture baselines of the current intermediate CSV output for every bank the app currently imports. After this task the repo contains a fully-wired but unused parser package, and every subsequent refactor task has a byte-exact regression oracle to test against.

This task ships no user-visible change. Its value is that Tasks 1–7 become safe to write because they have something to verify against.

## Context

This is Task 0 of an 8-task backend refactor that splits `Scripts/BankCSV.py` into a two-layer adapter/translator architecture under `app/backend/services/parsers/`. The full task sequence, decisions, and rationale are captured in memory (`project_csv_parser_refactor.md`). In one-line form:

- **Adapters** parse per-institution CSV text → stream of `Record` dataclasses.
- **Translators** turn `Record`s into `LedgerTransaction`/`Posting` structures that an intermediate writer (Task 1) serializes to the same intermediate CSV format today's pipeline produces.

The load-bearing constraint is **import identity hash stability** (ARCHITECTURE.md §"Import Pipeline and Identity Model"): `source_identity` and `source_payload_hash` are SHA-256 over the normalized intermediate, so any drift in the intermediate's byte-exact output makes previously imported transactions reappear as "new" on reimport. Task 0 establishes the golden fixtures that prove Tasks 1–7 didn't drift.

## Scope

### Included

**New files under `app/backend/services/parsers/`:**

- `__init__.py` — empty, marks the package
- `types.py` — `Record`, `Posting`, `LedgerTransaction` dataclasses and `Adapter`, `Translator` protocols
- `registry.py` — `_ADAPTERS` and `_TRANSLATORS` registries, `@register_adapter` / `@register_translator` decorators, `get_adapter`, `get_translator`, `list_adapters`, `list_translators`, `autodetect_adapter`, `discover`
- `implementations/__init__.py` — empty, marks the subpackage Tasks 2+ will populate

**New golden fixtures under `app/backend/tests/fixtures/csv_snapshots/`:**

- `wells_fargo/input.csv` — sanitized real Wells Fargo CSV. Must exercise regular debits, regular credits, a `CHECK #` entry, a `REF #` entry, and the headerless shape.
- `wells_fargo/expected_intermediate.csv` — byte-exact output of today's `normalize_csv_to_intermediate()` applied to `input.csv`.
- `alipay/input.csv` — sanitized Alipay sample. Must exercise income (收入) rows, expense (支出) rows, the 13-row preamble, the 1-row footer, GB18030 encoding, and non-Latin column/payee text.
- `alipay/expected_intermediate.csv` — byte-exact output.
- `icbc/input.csv` — sanitized ICBC sample. Must exercise USD and CNY amounts in the same file, the 美元 currency indicator mapping to USD, the 7-row preamble, the 2-row footer, and the debit/credit split columns.
- `icbc/expected_intermediate.csv` — byte-exact output.
- `bank_of_beijing/input.csv` — sanitized BJB sample. Must exercise the 1-row preamble, sign-prefix amounts (`+123.45` / `-67.89`), and the counterparty-name column (对方户名).
- `bank_of_beijing/expected_intermediate.csv` — byte-exact output.

**New test file under `app/backend/tests/`:**

- `test_csv_parser_fixtures.py` — one parameterized test `test_fixture_reproduces_expected_intermediate(institution)` that runs the current `normalize_csv_to_intermediate()` against each fixture's `input.csv` and asserts byte-exact equality with `expected_intermediate.csv`. Plus one small unit test for `autodetect_adapter()` using a local throwaway adapter class.

### Explicitly excluded

- **No modification to `csv_normalizer.py`, `institution_registry.py`, `custom_csv_service.py`, `import_service.py`, or `Scripts/BankCSV.py`.** The new `services/parsers/` package exists alongside them with zero integration.
- **No adapter or translator implementations.** `implementations/` is empty in this task. Tasks 2+ populate it.
- **No intermediate writer.** That's Task 1.
- **No changes to import identity, import service, import profile, import history, or any route handler.**
- **No removal of any legacy code.** Everything `Scripts/BankCSV.py` does today keeps working unchanged.
- **No securities/brokerage fields on `Record`** (`action`, `symbol`, `quantity`, `price`, `fees`). Deferred until brokerage support is a real feature.
- **No aggregator adapter** (Plaid/SimpleFIN/GoCardless). `Record` reserves fields for future aggregators but no aggregator code exists in this task.
- **No frontend changes whatsoever.**
- **No call to `discover()` from app startup.** The function exists so Tasks 2+ can call it from `csv_normalizer.py`; until then nothing invokes it.

## System Behavior

### Inputs

- Developer runs `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q`
- Developer imports `app.backend.services.parsers` from a REPL or another test
- No user-facing input; this task has no runtime surface

### Logic

**`services/parsers/types.py`:**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterator, Protocol, runtime_checkable


@dataclass
class Record:
    """Normalized output from an Adapter, input to a Translator.

    Cash fields are signed from the account holder's perspective:
    positive = money in, negative = money out.
    """
    date: date
    description: str

    amount: Decimal | None = None
    currency: str = "USD"
    counterparty: str | None = None
    code: str | None = None
    effective_date: date | None = None

    # Reserved for future aggregator adapters (Plaid, SimpleFIN, GoCardless).
    # CSV adapters leave these as defaults.
    provider_id: str | None = None
    pending: bool = False
    suggested_category: str | None = None
    provider_payee: str | None = None

    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Posting:
    account: str
    amount: Decimal | None = None
    commodity: str | None = None
    price: Decimal | None = None


@dataclass
class LedgerTransaction:
    date: date
    payee: str
    postings: list[Posting]
    effective_date: date | None = None
    code: str | None = None
    note: str | None = None


@runtime_checkable
class Adapter(Protocol):
    name: str
    institution: str
    formats: tuple[str, ...]

    def parse(self, text: str) -> Iterator[Record]: ...
    # matches(text, filename) -> bool is optional; adapters may omit it.
    # Account binding is the routing mechanism; autodetect is a future feature.


@runtime_checkable
class Translator(Protocol):
    name: str

    def translate(self, record: Record, account: str) -> LedgerTransaction: ...
```

Notes:
- `parse()` takes `text: str`, not `bytes` — `csv_normalizer.py` continues to own encoding and head/tail slicing (Option B).
- No securities fields on `Record`. Aggregator fields (`provider_id`, `pending`, `suggested_category`, `provider_payee`) default to None/False so CSV adapters can ignore them entirely.
- `matches()` is documented as optional in a comment, not in the protocol — Python's `Protocol` doesn't express optional methods cleanly. `autodetect_adapter()` uses `getattr(adapter, "matches", None)` to handle its absence.

**`services/parsers/registry.py`:**

```python
from __future__ import annotations
import importlib
import pkgutil
from typing import Optional

from .types import Adapter, Translator

_ADAPTERS: dict[str, Adapter] = {}
_TRANSLATORS: dict[str, Translator] = {}


def register_adapter(cls):
    """Class decorator: instantiate and register an Adapter."""
    instance = cls()
    if instance.name in _ADAPTERS:
        raise RuntimeError(f"Duplicate adapter name: {instance.name!r}")
    _ADAPTERS[instance.name] = instance
    return cls


def register_translator(cls):
    """Class decorator: instantiate and register a Translator."""
    instance = cls()
    if instance.name in _TRANSLATORS:
        raise RuntimeError(f"Duplicate translator name: {instance.name!r}")
    _TRANSLATORS[instance.name] = instance
    return cls


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS[name]


def get_translator(name: str) -> Translator:
    return _TRANSLATORS[name]


def list_adapters() -> list[Adapter]:
    return list(_ADAPTERS.values())


def list_translators() -> list[Translator]:
    return list(_TRANSLATORS.values())


def autodetect_adapter(text: str, filename: str) -> Optional[Adapter]:
    """Reserved for future autodetect-on-upload. Walks adapters that define
    a matches() method and returns the unique match, or None if 0 or >1 match.
    """
    hits = []
    for adapter in _ADAPTERS.values():
        matcher = getattr(adapter, "matches", None)
        if matcher is not None and matcher(text, filename):
            hits.append(adapter)
    return hits[0] if len(hits) == 1 else None


def discover() -> None:
    """Import every parsers/implementations/<name> subpackage so that
    @register_adapter and @register_translator decorators execute."""
    from . import implementations
    for _, name, is_pkg in pkgutil.iter_modules(implementations.__path__):
        if is_pkg:
            importlib.import_module(f"{implementations.__name__}.{name}")
```

`registry.py` imports only from `.types` and the standard library. No reverse dependency from `registry.py` to any implementation — `discover()` imports `implementations` lazily inside the function body.

**Golden-fixture generation (one-shot, not committed code):**

For each bank, the author:
1. Copies a real CSV from the workspace to a working directory.
2. Sanitizes the input: replace payee text with deterministic placeholders (`PAYEE_001`, `PAYEE_002`, ...), strip account numbers, preserve code-extraction patterns (`REF #XXXXX`, `CHECK #NNN`) literally, preserve the BOM and line endings exactly as the real file has them, preserve the original encoding (GB18030 for Alipay — write back as GB18030, not UTF-8).
3. Runs today's `normalize_csv_to_intermediate(config, sanitized_path, account_cfg)` with a minimal `AppConfig` and `account_cfg` that point at the sanitized input.
4. Captures the returned string to `expected_intermediate.csv`.
5. Commits both files under `tests/fixtures/csv_snapshots/<institution>/`.

Sanitization happens on the *input* first; the expected output is then regenerated from the sanitized input, never hand-edited.

**`test_csv_parser_fixtures.py`:**

```python
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "csv_snapshots"
INSTITUTIONS = ["wells_fargo", "alipay", "icbc", "bank_of_beijing"]


@pytest.mark.parametrize("institution", INSTITUTIONS)
def test_fixture_reproduces_expected_intermediate(institution):
    from app.backend.services.csv_normalizer import normalize_csv_to_intermediate
    # Load fixture, construct minimal AppConfig and account_cfg pointing at
    # the fixture input, invoke normalize_csv_to_intermediate, and assert
    # byte-exact equality with the fixture's expected_intermediate.csv.
    ...


def test_autodetect_adapter_returns_unique_match():
    from app.backend.services.parsers import registry
    from app.backend.services.parsers.types import Record

    class _FakeAdapter:
        name = "fake.test"
        institution = "fake"
        formats = ("csv",)
        def parse(self, text): return iter([])
        def matches(self, text, filename): return filename == "fake.csv"

    try:
        registry.register_adapter(_FakeAdapter)
        assert registry.autodetect_adapter("", "fake.csv").name == "fake.test"
        assert registry.autodetect_adapter("", "other.csv") is None
    finally:
        registry._ADAPTERS.pop("fake.test", None)
```

The exact `AppConfig` + `account_cfg` shape is whatever `csv_normalizer.py` expects today — the test is a characterization test against the current pipeline, not a unit test of the new parser package.

### Outputs

- New Python package at `app/backend/services/parsers/` with `types.py`, `registry.py`, and two empty `__init__.py` files. Importable but unused by the running backend.
- Four golden-fixture directories under `app/backend/tests/fixtures/csv_snapshots/` with sanitized `input.csv` and `expected_intermediate.csv` for each of Wells Fargo, Alipay, ICBC, Bank of Beijing.
- One new test file that runs the current pipeline against each fixture and asserts byte-exact output, plus a smoke test for `autodetect_adapter`.
- **Zero changes to any pre-existing file.** `git diff` on anything outside `services/parsers/` and `tests/fixtures/csv_snapshots/` and `tests/test_csv_parser_fixtures.py` is empty.

## System Invariants

- `services/csv_normalizer.py`, `services/institution_registry.py`, `services/custom_csv_service.py`, `Scripts/BankCSV.py`, and every import-pipeline consumer remain byte-identical after this task.
- Import identity (`source_identity`, `source_payload_hash`) is untouched. This task ships no code path that produces intermediate CSV output — it only records what the existing code path produces.
- The new `services/parsers/` package is not imported from anywhere in the running backend. It's only reachable through `pytest` or a deliberate REPL import. No API routes, no startup hooks, no implicit discovery.
- `discover()` is not called anywhere in the app's startup path in this task. It exists for Tasks 2+ to invoke from `csv_normalizer.py` once adapters exist to discover.
- The golden fixtures are sanitized. No real payee names, no real account numbers, no recognizable real-world merchants in the committed files. Real amounts and dates are acceptable only if they're not personally identifying in combination with the sanitized payees.
- `Record` reserves aggregator-friendly fields (`provider_id`, `pending`, `suggested_category`, `provider_payee`) with safe defaults. Tasks 2–7 must not remove these fields.

## States

Not applicable. This task ships no UI, no user-visible state, no runtime behavior, no failure modes that a user would perceive.

## Edge Cases

- **Real CSV unavailable for a bank.** If the author doesn't have a real sample on hand for a given bank, that fixture is blocked on obtaining one. Deferring one bank is acceptable if the deferred bank is noted in Delivery Notes, but the task does not ship without fixtures for at least **Wells Fargo + one Chinese bank** (ICBC or Alipay). Those two cover the two hardest existing code paths: headerless CSV and GB18030-encoded preamble-heavy CSV.
- **Sanitization breaks code-extraction patterns.** Replacing payee text with placeholders may accidentally remove the `REF #XXXXX` or `CHECK #NNN` patterns that `WellsFargoCSV.code()` depends on. Verify post-sanitization that each code-extraction branch (REF, CHECK, fallback-to-note, fallback-to-empty) is exercised by at least one row.
- **BOM handling.** Alipay files often begin with a UTF-8 or GB18030 BOM. The sanitized fixture must preserve the BOM exactly as the real file has it — stripping it silently makes today's parser produce different output on the fixture than on real files, and the baseline becomes worthless.
- **Trailing newline and line endings.** Some banks end their CSV with `\n`, some with `\r\n`, some with neither. The fixture must preserve whatever the real file has. Do not let an editor "tidy up" line endings during sanitization.
- **Encoding round-trip.** When saving a sanitized Alipay input back to disk, it must be written in GB18030, not UTF-8. Writing it as UTF-8 and then pointing the parser at it silently produces different output because the non-Latin column names decode wrong.
- **Deterministic placeholder collisions.** If sanitization replaces two distinct real payees with the same placeholder (e.g., both become `PAYEE_001`), the intermediate output still reproduces deterministically — but the fixture loses coverage of a duplicate-payee case. If the original file had rows that depended on unique payee text, use distinct placeholders.

## Failure Behavior

- **Golden test fails on first run.** The fixture was generated incorrectly — sanitization broke something, encoding mismatched, BOM missing, line endings changed. Fix the fixture, never touch the parser. The test's purpose is to catch author errors before Tasks 1+ rely on the baseline.
- **Import of `services.parsers` fails at module load.** `types.py` or `registry.py` has a syntax error or a circular import. Fix before landing.
- **`discover()` raises on empty `implementations/`.** `pkgutil.iter_modules` must return an empty iterator on an empty directory, not raise. Verify in a REPL before landing.
- **Sanitization leaks real data into the repo.** Hard failure — revert the commit, regenerate the fixture, re-verify. Treat fixture files with the same care as logs or backups: once committed, assume they're discoverable.
- **Pre-existing pytest environment issue.** Phase 4b's TASK.md noted that `uv run pytest -q` currently fails on `ModuleNotFoundError: fastapi` in some environments. If the author hits this, the test file still lands; acceptance degrades to "pytest collects and runs the new test file, and the only failures are the same pre-existing environment issue, not new ones caused by this branch." Document it in Delivery Notes if it happens.

## Regression Risks

- **Accidental integration.** Importing `services.parsers` from `csv_normalizer.py` or any other existing service at any point in this task would break its "zero-integration scaffolding" posture. Verification: `grep -rE "from .parsers|from app.backend.services.parsers|import parsers" app/backend/services/ --include='*.py'` returns matches only inside `services/parsers/` itself.
- **Circular import when `implementations/` grows later.** `registry.py` must only import from `.types` and the standard library. `discover()` must import `implementations` lazily inside its function body, not at module top-level. If `registry.py` ever imports an implementation module eagerly, Tasks 2+ will hit circular-import errors.
- **Golden fixtures drift between now and Task 7.** The committed baseline assumes `Scripts/BankCSV.py` is frozen. If someone patches `BankCSV.py` between this task and Task 7, Tasks 2+ will fail against a stale fixture even though they're correct. Mitigation: the `Scripts/BankCSV.py` file should be treated as frozen for the duration of the refactor; if a bug fix is needed there, regenerate the affected fixture in the same commit.
- **`autodetect_adapter` is dead code in this task.** It's included because Tasks 2+ will eventually need it and it's cheap to write now. A bug would hide until autodetect becomes a real feature. Mitigation: the `test_autodetect_adapter_returns_unique_match` smoke test above exercises the register/detect/cleanup path.
- **Fixture pollution from the smoke test.** If `_FakeAdapter` isn't cleaned up after `test_autodetect_adapter_returns_unique_match`, subsequent tests might see it in the registry. Mitigation: the test wraps registration in `try/finally` and pops the fake from `_ADAPTERS` after the assertions.
- **Schwab fixture missing by design.** The current `Scripts/BankCSV.py` supports Schwab, but Task 0 does not generate a Schwab fixture because Schwab is out of scope for the full refactor. If a reviewer expects fixtures for every bank in `institution_registry._REGISTRY`, remind them that Schwab gets deleted in Task 7 and fixtures for deleted paths are wasted work.

## Acceptance Criteria

- `app/backend/services/parsers/__init__.py`, `types.py`, `registry.py`, and `implementations/__init__.py` exist.
- `uv run python -c "from app.backend.services.parsers import types, registry; registry.discover(); print('ok')"` prints `ok` from the repo root.
- `Record`, `Posting`, `LedgerTransaction`, `Adapter`, `Translator` are all importable from `app.backend.services.parsers.types`.
- `Record` has all fields listed in the Logic section, including the aggregator-friendly fields `provider_id`, `pending`, `suggested_category`, `provider_payee` with their documented defaults.
- `register_adapter`, `register_translator`, `get_adapter`, `get_translator`, `list_adapters`, `list_translators`, `autodetect_adapter`, `discover` are all importable from `app.backend.services.parsers.registry`.
- Golden fixtures exist under `app/backend/tests/fixtures/csv_snapshots/` for `wells_fargo`, `alipay`, `icbc`, and `bank_of_beijing` (or at least Wells Fargo + one Chinese bank, with the deferred fixtures documented in Delivery Notes). Each directory contains both `input.csv` and `expected_intermediate.csv`.
- `test_csv_parser_fixtures.py` runs. Every shipped fixture is green. The only acceptable failure is the pre-existing `fastapi` environment issue from Phase 4b, documented in Delivery Notes.
- `grep -rE "from .parsers|from app.backend.services.parsers|import parsers" app/backend/services/ --include='*.py' | grep -v 'services/parsers/'` returns no matches.
- `git diff --stat HEAD~N -- 'app/backend/services/' ':!app/backend/services/parsers/'` shows zero pre-existing backend service files modified (for appropriate N covering this task's commits).
- `git diff --stat HEAD~N -- Scripts/` shows zero changes.
- Spot-check: grep a committed fixture for any name, merchant, or account number the author recognizes from real usage. No hits.

## Proposed Sequence

1. **Package skeleton.** Create `services/parsers/__init__.py`, `types.py`, `registry.py`, `implementations/__init__.py`. Write the dataclasses and protocols in `types.py`; the decorators, accessors, `autodetect_adapter`, and `discover` in `registry.py`.
2. **Smoke-verify imports.** From the repo root: `uv run python -c "from app.backend.services.parsers import types, registry; registry.discover(); print('ok')"`. Fix any import errors before proceeding. Commit the skeleton.
3. **Wells Fargo fixture first.** Grab a real WF CSV, sanitize payees (preserve `CHECK #` and `REF #` patterns), write to `tests/fixtures/csv_snapshots/wells_fargo/input.csv`. Run today's `normalize_csv_to_intermediate()` on it from a throwaway script or REPL, capture the output to `expected_intermediate.csv`. Commit both files.
4. **Test file with WF only.** Write `test_csv_parser_fixtures.py` with the parameterization limited to `["wells_fargo"]`. Run `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q`. Must be green. Commit.
5. **Alipay fixture.** GB18030, 13-row preamble, 1-row footer. Sanitize non-Latin payee text to deterministic placeholders (write a small helper if needed). Preserve BOM and line endings. Re-save in GB18030, not UTF-8. Generate expected output, commit both files, extend the test parameterization to include `alipay`, verify green.
6. **ICBC fixture.** 7-row preamble, 2-row footer, USD+CNY mixed rows, 美元 currency indicator. Sanitize, generate expected, extend parameterization, verify green.
7. **BJB fixture.** 1-row preamble, sign-prefix amounts, counterparty column. Sanitize, generate expected, extend parameterization, verify green.
8. **Autodetect smoke test.** Add `test_autodetect_adapter_returns_unique_match` with the local throwaway adapter class. Verify green.
9. **Zero-integration verification.** Run the grep commands from Acceptance Criteria. Confirm no pre-existing file was touched. Run `git diff --stat` against the branch point to verify only new files.
10. **Final commit and Delivery Notes.** Fill in Delivery Notes below with the commit hashes, the pytest outcome (pass or pre-existing `fastapi` failure only), and any deferred fixture.

Commit granularity: one commit for the package skeleton (step 1), one commit per fixture+test-extension pair (steps 3–7), one commit for the autodetect smoke test (step 8). Bisect-friendly.

## Definition of Done

- All acceptance criteria met.
- `services/parsers/` imports cleanly from a fresh REPL.
- `test_csv_parser_fixtures.py` is green for every committed fixture (or fails only on the pre-existing `fastapi` environment issue, documented in Delivery Notes).
- `Scripts/BankCSV.py`, `csv_normalizer.py`, `institution_registry.py`, `custom_csv_service.py`, and every non-`parsers/` file under `services/` is untouched.
- No committed fixture contains identifying information beyond what a reasonable reviewer would consider sanitized.
- The task leaves the tree in the exact state Task 1 expects: a scaffold ready to receive the intermediate writer, with golden fixtures ready to regress-test it.

## Upcoming Tasks (for reference — not Task 0 scope)

1. **Task 1 — Intermediate serializer.** Write `services/parsers/intermediate_writer.py` consuming `LedgerTransaction` streams, producing the same intermediate CSV bytes as today. Cash-only (no commodity-posting rendering — Schwab is out of scope). Unit tests against the Task 0 fixtures.
2. **Task 2 — Wells Fargo adapter + `generic.checking` translator** behind a `use_new_parser` config flag. Golden test must match the Task 0 WF fixture byte-exact before flipping the flag.
3. **Task 3 — `generic.credit` translator.** Single-file add. No institution ports.
4. **Task 4 — Alipay adapter.** GB18030 + 13/1 slicing. Stress-tests the adapter plumbing; may require a `BaseAdapter` refactor if per-adapter slicing duplication gets painful.
5. **Task 5 — ICBC adapter.** USD/CNY currency-from-column, 7/2 slicing. Validates the base class from Task 4.
6. **Task 6 — BJB adapter + derive `institution_registry` from the adapter registry.** `_REGISTRY` becomes generated state.
7. **Task 7 — Delete `Scripts/BankCSV.py`.** Must ship as its **own isolated git commit** so the Schwab implementation is easy to locate in history if brokerage support lands later. Per-user instruction captured in project memory.

## Out of Scope

- Any adapter or translator implementation (Tasks 2+).
- Intermediate writer (Task 1).
- `csv_normalizer.py` routing changes.
- Derivation of `institution_registry` from the adapter registry (Task 6).
- Deletion of `Scripts/BankCSV.py` (Task 7).
- Schwab/brokerage support in any form.
- Autodetect-on-upload UI.
- Plaid, SimpleFIN, GoCardless, or any aggregator adapter.
- Privacy-oriented removal of the public "supported institutions" list.
- Fixing the pre-existing `fastapi` pytest environment issue.

## Delivery Notes

**Status: COMPLETE — landed 2026-04-14**

### Commits (in order)

1. `4c2e9b5` — `feat(parsers): scaffold services/parsers package skeleton`
2. `9b05815` — `test(parsers): add Wells Fargo golden fixture for CSV import refactor`
3. `20187fd` — `test(parsers): add Alipay golden fixture (GB18030 + 13/1 slicing)`
4. `a8a0066` — `test(parsers): add ICBC golden fixture (USD+CNY mixed currency)`
5. `4dc4daf` — `test(parsers): add autodetect_adapter smoke test`
6. (this commit) — `docs: record Task 0 delivery notes`

### Fixtures shipped vs deferred

- **Wells Fargo** — shipped. Sourced from `workspace/imports/processed/2026/wells_fargo_checking_4770/2026__wells_fargo_checking_4770__Checking1-1-036de688-74786d4a218f.csv` (the file with the broadest pattern coverage). Exercises regular debits, regular credits, multiple `REF #` rows, and three `CHECK #` rows where the bank populates the note column. **Gap:** the `CHECK # in description with empty note` branch of `WellsFargoCSV.code()` is not exercised — the source data never produces that shape (every CHECK row in the real export populates the note column with the check number, so branch 1 always fires before branch 3). I chose not to synthesize a row to cover that branch because synthetic rows in a regression-oracle fixture are worse than a documented gap. Tasks 2 and beyond should add a unit test for that branch directly against the new Wells Fargo adapter once it lands.
- **Alipay** — shipped. Sourced from `workspace/imports/2024-alipay.csv`. Encoded as GB18030, LF line endings, 13-row preamble, 1-row footer. Body trimmed from 233 source rows to 12 representative rows (3 income / 9 expense), enough to exercise the income/expense split-column branches without inflating the fixture file.
- **ICBC** — shipped. Sourced from `workspace/imports/2025-icbc.csv`. Encoded as UTF-8 with BOM, CRLF line endings, 7-row preamble, 2-row footer. The source file is CNY-only, so a single synthetic USD row was added at the top of the body to exercise the `美元 -> USD` branch in `IcbcCSV.currency()` and the USD path in `IcbcCSV.amount()`. Without it the regression oracle would not catch a refactor that broke the USD mapping. Body has 6 rows total: 1 USD expense, 4 CNY expense (different shapes), 1 CNY income (退款) row.
- **Bank of Beijing** — **deferred**. Reason: no BJB sample on this machine. The fixture will land with Task 6 (BJB adapter) so the sanitization, generation, and characterization can happen against a real source file when one becomes available. The senior-developer brief explicitly authorized this deferral.

### Verification outcomes

All Acceptance Criteria checks pass. Literal stdout is reproduced in the agent report.

- `uv run python -c "from app.backend.services.parsers import types, registry; registry.discover(); print('ok')"` → `ok`
- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q` → `4 passed in 0.02s` (3 fixture parametrizations + 1 autodetect smoke test)
- `grep -rE "from .parsers|from app.backend.services.parsers|import parsers" app/backend/services/ --include='*.py' | grep -v 'services/parsers/'` → empty (no integration into pre-existing services)
- `git diff --stat 08e64a4..HEAD` → only new files under `app/backend/services/parsers/`, `app/backend/tests/fixtures/csv_snapshots/`, and `app/backend/tests/test_csv_parser_fixtures.py`, plus this Delivery Notes block. Zero pre-existing backend service files modified, zero `Scripts/` changes.
- Spot-grep for real-world identifiers in committed fixtures (merchant names, account fragments, holder name) → empty. Sanitization is clean.

### Pre-existing environment issue

Confirmed: running `uv run pytest app/backend/tests/ -q` aborts collection because `test_unknown_stage_resume.py` and `test_workspace_bootstrap.py` import `main`, which imports `fastapi`, which is not installed in this environment. This is the same pre-existing issue Phase 4b documented; it is unrelated to this branch. With those two test modules excluded (`--ignore=app/backend/tests/test_unknown_stage_resume.py --ignore=app/backend/tests/test_workspace_bootstrap.py`), the full backend suite passes (282 tests). The new fixture test file runs cleanly in isolation and does not introduce any new failure.

### Ambiguity resolved

- **Test import path.** The smoke acceptance criterion uses `from app.backend.services.parsers import ...` (run from worktree root, namespace-package style). Inside the test file, however, the `conftest.py` at `app/backend/tests/conftest.py` puts `app/backend` on `sys.path`, so other tests use `from services.X` directly. The new test file follows the in-test convention (`from services.csv_normalizer import ...`, `from services.parsers import registry`) to match the rest of the suite. Both paths resolve to the same module and both are exercised by the verification commands.
- **ICBC USD coverage.** See "Fixtures shipped" above. One synthetic row was added; the alternative (defer the entire ICBC fixture or ship it without USD coverage) was worse than a clearly-documented synthetic addition.
- **Wells Fargo CHECK branch 3.** See "Fixtures shipped" above. Not synthesized; documented gap instead.
