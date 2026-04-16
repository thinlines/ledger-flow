# Task 02 — Wells Fargo Adapter + Dispatch Seam

## Title

Wire the `services/parsers/` package into `csv_normalizer.py`, ship the Wells Fargo adapter and `generic.checking` translator, and route all Wells Fargo imports through the new pipeline while leaving every other institution on the legacy `Scripts/BankCSV.py` path.

## Objective

Establish the one-and-only dispatch seam that every subsequent adapter (Tasks 04, 05) will register against. After this task, a Wells Fargo CSV import produces byte-exact the same intermediate CSV as before, verified by the existing `test_csv_parser_fixtures.py[wells_fargo]` oracle. Alipay / ICBC / BJB / Schwab imports continue to run through the legacy `create_bank_csv()` factory unchanged.

## Context

Task 01 shipped the intermediate writer. This task is the first use of it in the live pipeline. The seam design needs to be simple enough that Tasks 04 and 05 only add new files in `implementations/` — they must never have to touch `csv_normalizer.py` again.

Registration is the gate: if `registry.get_adapter(institution_id)` finds one, the seam routes through it; otherwise it falls through to `_load_create_bank_csv()`. There is no `use_new_parser` config flag — the locked memory decision mentioned one, but registration-as-gate is a simpler and equally safe revert mechanism in a single-user self-hosted app. **Decision Needed from user if they'd prefer an explicit flag; default plan is no flag.**

## Scope

### Included

**Modify `app/backend/services/csv_normalizer.py`:**

After head/tail slicing (currently lines 42–46), add the dispatch branch **before** the `create_bank_csv` call:

```python
from .parsers import registry

# One-shot discover so implementations/*.py modules register their adapters.
registry.discover()

text = "".join(sliced)  # sliced is list[str]; join into the text the adapter receives
adapter = registry._ADAPTERS.get(institution_template_id)  # or registry.get_adapter(...) with catch
if adapter is not None:
    translator_name = getattr(adapter, "translator_name", None)
    if translator_name is None:
        raise RuntimeError(
            f"Adapter {adapter.name!r} did not declare translator_name; "
            f"cannot route without an explicit translator"
        )
    translator = registry.get_translator(translator_name)
    account = str(account_cfg["ledger_account"])

    records = adapter.parse(text)
    transactions = [translator.translate(r, account) for r in records]
    # Legacy pipeline reverses output rows; preserve that for byte-exact parity.
    transactions.reverse()
    return write_intermediate(transactions)

# Legacy fallback
create_bank_csv = _load_create_bank_csv()
...
```

Design notes to carry into the implementation:

- `registry.discover()` is idempotent and cheap (decorators short-circuit on duplicate names with a clear error). Call it eagerly at the top of `normalize_csv_to_intermediate()`; an LRU-cached helper is optional.
- Adapter lookup is by institution slug only. Translator lookup is by name, declared as a `translator_name: str` class attribute on the adapter. This is the only protocol extension beyond Task 0 — document it in `types.py` as a comment on the `Adapter` protocol.
- `text` passed to `adapter.parse()` is the joined sliced lines (already decoded per the institution's encoding, already head/tail-trimmed). Adapters get a string; they never touch the file or encoding.
- Reversal happens in the seam, not in the adapter or writer. Matches legacy behavior (`reversed(output_rows)` on line 77 today).
- The legacy fallback must continue to work for Alipay, ICBC, BJB, Schwab, and any custom institution until its adapter lands.

**New file `app/backend/services/parsers/implementations/wells_fargo.py`:**

Single module declaring both the adapter and the shared `generic.checking` translator:

```python
from __future__ import annotations
import csv
import io
import re
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter, register_translator
from ..types import LedgerTransaction, Posting, Record


@register_translator
class GenericCheckingTranslator:
    """Cash-account translator. One posting per transaction (tracked-account
    side). The other leg is synthesized later by ledger convert + rules."""
    name = "generic.checking"

    def translate(self, record: Record, account: str) -> LedgerTransaction:
        return LedgerTransaction(
            date=record.date,
            payee=record.description,
            code=record.code,
            note=record.note,
            balance=record.balance,
            postings=[Posting(
                account=account,
                amount=record.amount,
                commodity=record.currency,
            )],
        )


@register_adapter
class WellsFargoAdapter:
    name = "wells_fargo"
    institution = "wells_fargo"
    formats = ("csv",)
    translator_name = "generic.checking"

    _REF_RE = re.compile(r"REF #(\S+)")
    _CHECK_RE = re.compile(r"CHECK # (\d+)")

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            # Headerless WF format: date, amount, cleared, note, description
            yield Record(
                date=datetime.strptime(row[0], "%m/%d/%Y").date(),
                description=row[4],
                amount=Decimal(row[1]),
                currency="$",
                code=self._extract_code(row[3], row[4]),
                note=None if self._extract_code(row[3], row[4]) else (row[3] or None),
                balance=None,  # WF CSV has no running-balance column
                raw={"cleared": row[2]},
            )

    def _extract_code(self, note: str, description: str) -> str | None:
        # Matches WellsFargoCSV.code() in Scripts/BankCSV.py line ~300.
        # Precedence: note column > REF # in description > CHECK # in description.
        ...
```

The exact `_extract_code` precedence must match `WellsFargoCSV.code()` in `Scripts/BankCSV.py`. Read that method before writing the adapter; reproduce its branches literally. The unit test in this task exercises every branch against real fixture rows.

**New file `app/backend/tests/test_wells_fargo_adapter.py`:**

- Adapter-level unit tests: construct a small WF CSV text snippet, parse it, assert Record contents row-by-row (date, amount, code, description, note, balance=None, currency="$").
- Explicitly exercise every branch of `_extract_code`: (a) REF # match in description, (b) CHECK # match in description with empty note column, (c) CHECK # match with note column populated (note takes precedence per `WellsFargoCSV.code()`), (d) neither match, note column empty, (e) neither match, note column populated.
- Translator-level unit test: construct a Record with each combination of {balance=None, balance=Decimal}, {note=None, note="text"}, {currency="$", currency="USD"}; assert the resulting LedgerTransaction shape.
- End-to-end test (through the seam): call `normalize_csv_to_intermediate()` with a minimal AppConfig containing only `wells_fargo` in `institution_templates`, the fixture's `input.csv` path, and a minimal `account_cfg` with `institution="wells_fargo"` and `ledger_account="Assets:Bank:Wells Fargo:Checking"`. Assert byte-exact equality with `app/backend/tests/fixtures/csv_snapshots/wells_fargo/expected_intermediate.csv`. This is a duplicate of what `test_csv_parser_fixtures.py[wells_fargo]` already checks, but isolates failure to this adapter.

**No changes to `test_csv_parser_fixtures.py`:** the existing parameterized test now exercises the new pipeline for WF by virtue of the seam dispatching to the registered adapter. Do not modify it.

### Explicitly excluded

- No other adapters. Alipay, ICBC, BJB, Schwab stay on `Scripts/BankCSV.py`.
- No `generic.credit` translator — cut as YAGNI (2026-04-15 scope trim).
- No changes to `institution_registry.py`, `import_service.py`, `custom_csv_service.py`, or any route handler.
- No frontend changes.
- No `use_new_parser` config flag (unless the user requests one — see note above).
- No Schwab-related changes.
- No changes to `Scripts/BankCSV.py`.

## System Behavior

**Inputs:** same as today — `normalize_csv_to_intermediate(config, csv_path, account_cfg)`.

**Logic (new):**

1. Resolve institution and encoding (unchanged from today).
2. If institution mode is `"custom"` → delegate to `normalize_custom_csv_to_intermediate` (unchanged).
3. Read file, slice head/tail (unchanged).
4. `registry.discover()` → import every `implementations/*.py` so decorators run.
5. Look up `registry.get_adapter(institution_template_id)`. If found:
   - Look up `translator = registry.get_translator(adapter.translator_name)`.
   - `records = adapter.parse("".join(sliced))`.
   - `transactions = [translator.translate(r, ledger_account) for r in records]`.
   - `transactions.reverse()`.
   - `return write_intermediate(transactions)`.
6. Otherwise → fall through to legacy `_load_create_bank_csv()` path (unchanged).

**Outputs:** intermediate CSV string, byte-identical to today for every institution.

## System Invariants

- Byte-exact intermediate for Wells Fargo: `test_csv_parser_fixtures.py[wells_fargo]` green.
- Byte-exact intermediate for every non-WF institution: `test_csv_parser_fixtures.py[alipay]` and `[icbc]` still green via the legacy fallback.
- `Scripts/BankCSV.py` unchanged.
- The dispatch seam has no per-institution branching. It looks up adapter by slug, and that's it. Every future adapter registers into this same seam.
- `adapter.translator_name` is the only protocol extension beyond Task 0.
- `registry.discover()` is idempotent and safe to call multiple times.
- No adapter or translator is imported eagerly by `csv_normalizer.py` — only through `registry.discover()`, preserving the "no reverse dependency from registry to implementations" rule from Task 0.

## States

Not applicable — no UI.

## Edge Cases

- **Adapter raises during `parse()`.** Let the exception propagate. `csv_normalizer` does not catch. The user-facing import preview will show the error; same blast radius as a legacy BankCSV error today.
- **Translator missing after adapter is registered.** `registry.get_translator(adapter.translator_name)` raises `KeyError`. This is a developer error — surface loudly.
- **Adapter and legacy `BankCSV` subclass both exist for the same institution.** The seam routes to the adapter first; the legacy fallback never fires. For WF during this task, this is expected and intentional — the golden test verifies the adapter's output equals the legacy output.
- **Account config missing `ledger_account`.** Adapter test passes it explicitly; production path always has it (set during account setup). Raise `KeyError` if absent — fail closed.
- **WF CSV row with malformed date.** Legacy raises `ValueError` from `strptime`. Adapter does the same (uses `datetime.strptime`).

## Failure Behavior

- **Dispatch seam import error.** If `from .parsers import registry` fails at module load, the entire `csv_normalizer` module fails. This is a correctness-over-robustness choice — a broken parser package should not silently fall through to legacy.
- **`registry.discover()` raises.** An implementation module has a circular import or syntax error. Let it propagate; the broken module must be fixed before imports can proceed.
- **Adapter output fails the byte-exact golden test.** The adapter is wrong; fix the adapter. **Never** modify the golden fixture to match the adapter.
- **Duplicate adapter/translator name registration.** `registry.register_adapter` / `register_translator` raises `RuntimeError` with the duplicate name. Task 0 already wired this.

## Regression Risks

- **Silent change to Alipay/ICBC/Schwab/custom output.** The seam only routes when `adapter is not None`. Verify: `test_csv_parser_fixtures.py[alipay]` and `[icbc]` still green.
- **`sliced` concatenation loses bytes.** `"".join(sliced)` where `sliced` is `list[str]` must faithfully round-trip to the same text that `BankCSV.reader()` would consume. Verify the WF fixture golden test stays byte-exact.
- **Reversal ordering mismatch.** Legacy reverses `output_rows` (after the CSV-row → intermediate-row conversion). New pipeline reverses after translator output but before writer. If the reversal is one step off, the intermediate is in the wrong order. Mitigated by the byte-exact golden.
- **`registry._ADAPTERS.get(...)` on bare-module access.** If the seam reaches into the private `_ADAPTERS` dict, refactoring `registry.py` later could break it. Use the public `registry.get_adapter()` API and catch `KeyError` instead.
- **`translator_name` typo.** `"generic.checking"` in the adapter must match the translator's `name` attribute exactly. Single-source the string in a module-level constant (e.g., `GENERIC_CHECKING = "generic.checking"`) and reference both registration and adapter from it.
- **WF `_extract_code` divergence from `WellsFargoCSV.code()`.** Line-by-line comparison required. Golden test catches output drift but not all edge cases (Task 0 noted the "CHECK # in description with empty note" branch isn't exercised by the fixture). Adapter unit tests must exercise every branch directly.
- **Side effects on `custom_csv_service`.** Custom profiles route through `normalize_custom_csv_to_intermediate` before the seam fires. Custom path unaffected.

## Acceptance Criteria

- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q` is green (all three institutions).
- `uv run pytest app/backend/tests/test_wells_fargo_adapter.py -q` is green.
- `uv run python -c "from app.backend.services.parsers import registry; registry.discover(); a = registry.get_adapter('wells_fargo'); print(a.translator_name)"` prints `generic.checking`.
- `grep -rE "from .*parsers" app/backend/services/csv_normalizer.py` shows the `from .parsers import registry` import (one entry).
- `grep -rE "Scripts/BankCSV|_load_create_bank_csv" app/backend/services/` shows the fallback still wired (the legacy code path is reachable for non-WF institutions).
- `git diff --stat` shows: `csv_normalizer.py` modified; `types.py` maybe modified (only the documentation comment about `translator_name`); `implementations/wells_fargo.py` added; `test_wells_fargo_adapter.py` added. No other files.
- `Scripts/BankCSV.py` is byte-identical to before this task.

## Proposed Sequence

1. **Protocol doc update.** In `types.py`, add a comment on `Adapter`: `# translator_name: str — class attribute naming the translator this adapter pairs with. Required by the dispatch seam in csv_normalizer.`. Commit.
2. **Translator implementation.** Write `GenericCheckingTranslator` in `implementations/wells_fargo.py`. Unit test against Record instances (no CSV, no adapter). Commit.
3. **WF adapter.** Write `WellsFargoAdapter` in the same file, including `_extract_code` with literal fidelity to `WellsFargoCSV.code()`. Unit-test every code-extraction branch. Commit.
4. **Dispatch seam.** Modify `csv_normalizer.py`. Confirm `test_csv_parser_fixtures.py[alipay]` and `[icbc]` still pass (legacy fallback intact). Commit.
5. **End-to-end verification.** `test_csv_parser_fixtures.py[wells_fargo]` must now route through the adapter. If it fails, the adapter is wrong — do not touch the fixture. Commit only when green.
6. **Delivery notes.** Record adapter code hashes and confirm the legacy WF path is no longer exercised in production for registered institutions. Commit.

Commit granularity: one commit per step above. Bisect-friendly.

## Definition of Done

- All Acceptance Criteria met.
- The Task 0 existing parameterized test is now proving the new pipeline for Wells Fargo.
- Alipay and ICBC still route through the legacy path and produce byte-exact output.
- Schwab (un-fixtured) still imports correctly through the legacy path — manually verified if a Schwab CSV is available.
- The seam design is the stable contract Tasks 04 and 05 build against.

## Dependencies

- **Depends on Task 01**: `write_intermediate` must exist and be importable.

## Out of Scope

- Alipay and ICBC adapters (Tasks 04, 05).
- `generic.credit` translator — cut as YAGNI (2026-04-15 scope trim).
- BJB adapter — cut as YAGNI; BJB removed from `institution_registry` in Task 07.
- `institution_registry` refactor (Task 06b).
- Deletion of `Scripts/BankCSV.py` (Task 07).
- Frontend, API, or config changes.
- Per-institution amount/total formatting overrides — if any real-world WF CSV breaks byte-exactness and the writer's general-purpose formatting rules don't cover it, escalate to a contract change and amend this task rather than patch around it.
