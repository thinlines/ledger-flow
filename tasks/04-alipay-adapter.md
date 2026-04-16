# Task 04 — Alipay Adapter

## Title

Port `AlipayCSV` (Scripts/BankCSV.py:99-126) to an adapter under `services/parsers/implementations/alipay.py`, reusing `generic.checking` translator. Route Alipay imports through the new pipeline.

## Objective

After this task, `normalize_csv_to_intermediate()` for Alipay CSVs produces byte-exact the same intermediate CSV as before, verified by `test_csv_parser_fixtures.py[alipay]` running end-to-end through the new adapter.

## Context

Alipay CSVs arrive as GB18030-encoded text with an 13-row preamble and 1-row footer. `csv_normalizer.py` owns decoding and head/tail slicing (per Task 0 locked design — Option B); the adapter receives already-decoded, already-sliced text. No special headerless handling is needed — Alipay CSVs contain the header row.

Reference implementation: `Scripts/BankCSV.py:99-126`. Golden fixture: `app/backend/tests/fixtures/csv_snapshots/alipay/{input,expected_intermediate}.csv`.

Reference behavior observed in the fixture (`app/backend/tests/fixtures/csv_snapshots/alipay/expected_intermediate.csv`):

- Amount formatting: `¥-7.80`, `¥500.00` — prefix currency `¥` (1-char), no thousand separator.
- Total formatting: `¥-332.50`, `¥90.00` — prefix currency `¥`, no thousand separator in the observed values. (Observed amounts are < 1000; writer's `:,` format is still correct since it produces no comma when unneeded.)
- Signs: the source Alipay CSV carries signs directly in the 收入 / 支出 columns (e.g., 支出 column contains `-7.80` for expenses, 收入 column contains `500.00` for income). `AlipayCSV.amount()` concatenates `self.currency + row["收入"] + row["支出"]`; the sign flows through from the non-empty column.
- Description: matches `AlipayCSV.description()` — returns `row["名称"].strip()` literally, so whatever multi-character content is in 名称 (e.g., `支付-PAYEE_005 购物`) becomes the intermediate's description.

## Scope

### Included

**New file `app/backend/services/parsers/implementations/alipay.py`:**

```python
from __future__ import annotations
import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Iterator

from ..registry import register_adapter
from ..types import Record


@register_adapter
class AlipayAdapter:
    name = "alipay"
    institution = "alipay"
    formats = ("csv",)
    translator_name = "generic.checking"

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            income = row.get("收入", "").strip()
            expense = row.get("支出", "").strip()
            # Alipay source has signs embedded: income positive, expense negative.
            # Matches Scripts/BankCSV.py:122 amount() behavior.
            raw_amount = (income or "") + (expense or "")
            yield Record(
                date=datetime.strptime(row["时间"].strip(), "%Y-%m-%d").date(),
                description=row["名称"].strip(),
                amount=Decimal(raw_amount) if raw_amount else None,
                currency="¥",
                code=row["流水号"].strip() or None,
                balance=Decimal(row["账户余额（元）"].strip()) if row.get("账户余额（元）", "").strip() else None,
                note=None,  # AlipayCSV does not override BankCSV.note(); always None.
                raw={k: v for k, v in row.items() if v},
            )
```

Column names to read (must match `AlipayCSV.__init__` at `Scripts/BankCSV.py:105-114`): `流水号`, `时间`, `名称`, `备注`, `收入`, `支出`, `账户余额（元）`, `资金渠道`.

**New file `app/backend/tests/test_alipay_adapter.py`:**

- Adapter-level unit tests using literal UTF-8 CSV text excerpts:
  - An income row (收入 populated, 支出 empty) → Record with positive amount.
  - An expense row (支出 populated with minus sign, 收入 empty) → Record with negative amount.
  - A row with populated 备注 column → Record.note still `None` (matches legacy behavior).
  - A row with non-ASCII 名称 → Record.description round-trips the characters exactly.
- End-to-end test: call `normalize_csv_to_intermediate()` with the Task 0 Alipay fixture as input; assert byte-exact equality with `expected_intermediate.csv`. This is a duplicate of what `test_csv_parser_fixtures.py[alipay]` already checks, but isolates failure to this adapter.

**No modification to `test_csv_parser_fixtures.py`:** the existing parameterized test covers Alipay by virtue of the dispatch seam routing to the registered adapter.

**No modification to `csv_normalizer.py`:** the dispatch seam from Task 02 already routes by institution slug.

### Explicitly excluded

- No fixture changes (Task 0 shipped the Alipay fixture; this task consumes it).
- No changes to `Scripts/BankCSV.py` — `AlipayCSV` stays in place until Task 07.
- No changes to `institution_registry.py` (Task 06b handles derivation).
- No new translator — reuses `generic.checking` from Task 02.
- No frontend, API, or config changes.

## System Behavior

**Inputs:** pre-decoded GB18030 text, header row intact, preamble/footer already sliced off by `csv_normalizer.py`.

**Logic:** DictReader → parse each row into a `Record`. Currency is always `¥`. Amount is signed from the 收入/支出 concatenation. Balance comes from 账户余额（元）. Note is always `None`. Code is 流水号.

**Outputs:** `Iterator[Record]`.

## System Invariants

- Record emission order matches the source CSV row order (newest-first in the Alipay input; the seam reverses before passing to the writer to preserve the oldest-first intermediate convention).
- `Record.currency == "¥"` for every Alipay record. Multi-currency is out of scope for this adapter.
- `Record.note` is always `None` — do not synthesize notes from 备注 or other columns. Matches the legacy `BankCSV.note() -> None` default that `AlipayCSV` did not override.
- `AlipayAdapter.translator_name == "generic.checking"`.
- The Task 0 Alipay fixture continues to pass byte-exact after this task.

## States

Not applicable.

## Edge Cases

- **Empty 收入 and empty 支出.** Legacy behavior: `amount() = currency + "" + ""` = `¥`. This would produce a malformed intermediate CSV row. The adapter emits `Record.amount = None` in this case, and the writer will raise `ValueError("Primary posting amount is required")` per Task 01. This is a correctness improvement over legacy — if Alipay CSVs in production ever hit this, surface it loudly rather than produce malformed output. **Validation step:** grep the Task 0 Alipay fixture for empty-收入/empty-支出 rows before writing the adapter; if any exist, re-examine this decision.
- **Row with non-empty 备注.** Legacy drops 备注 entirely. Adapter preserves it in `Record.raw["备注"]` but sets `Record.note = None` so the intermediate's note column stays empty. Byte-exact preserved.
- **GB18030-specific characters in 名称.** Pass through verbatim. The adapter receives already-decoded text; Python strings are Unicode; round-trip to UTF-8 for the intermediate CSV.
- **Header row variations.** DictReader reads field names from the first row. If a future Alipay CSV version has different column headers, the adapter breaks loudly on the missing `row["时间"]` key. Do not silently fall back.
- **Trailing whitespace on cell values.** Legacy `.strip()`s each field. Adapter does the same.

## Failure Behavior

- **Malformed date.** `datetime.strptime` raises `ValueError`. Propagate.
- **Malformed amount (non-numeric 收入/支出).** `Decimal()` raises `decimal.InvalidOperation`. Propagate.
- **Missing required column in header.** `row["时间"]` raises `KeyError`. Propagate.
- **Byte-exact fixture test fails.** The adapter is wrong. Never modify the fixture.

## Regression Risks

- **Byte-exact divergence from legacy.** Possible causes: different date format, different sign handling, extra whitespace, different currency symbol (legacy uses `¥` — one code point U+00A5; adapter must use the same). Mitigated by `test_csv_parser_fixtures.py[alipay]` running end-to-end.
- **Registration conflict.** Adapter name `"alipay"` must not collide with any existing registered adapter. Task 02 only registered `"wells_fargo"`; verify `registry.list_adapters()` shows both.
- **CSV BOM handling.** Alipay files may carry a BOM. `csv_normalizer.py` opens with the institution's encoding (`GB18030` for Alipay — [institution_registry.py line for alipay]); `csv.DictReader` on the decoded text should tolerate the BOM as whitespace in the first column name. Verify the adapter's `row.get()` calls still find `"流水号"` even if BOM-prefixed.
- **Sign interpretation.** If the fixture's 支出 column actually stores **unsigned** values (positive `9.90` for a $9.90 expense) and the sign is implicit in the column choice, the current adapter would emit a positive `Record.amount`, and the intermediate CSV's amount column would read `¥9.90` instead of `¥-9.90`. Before writing the adapter, **inspect `app/backend/tests/fixtures/csv_snapshots/alipay/input.csv` directly** to confirm the sign convention. If 支出 is unsigned, the adapter must prepend `-` manually (mirroring ICBC's approach).

## Acceptance Criteria

- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q` is green (all three institutions, including Alipay routing through the new adapter).
- `uv run pytest app/backend/tests/test_alipay_adapter.py -q` is green.
- `uv run python -c "from app.backend.services.parsers import registry; registry.discover(); a = registry.get_adapter('alipay'); print(a.translator_name, a.institution)"` prints `generic.checking alipay`.
- `grep -rE "alipay" Scripts/BankCSV.py` still finds `AlipayCSV` (BankCSV.py unchanged).
- `git diff --stat` shows: `implementations/alipay.py` added; `tests/test_alipay_adapter.py` added. No other files touched.

## Proposed Sequence

1. **Read `Scripts/BankCSV.py:99-126` carefully** and the `app/backend/tests/fixtures/csv_snapshots/alipay/input.csv` to confirm sign convention in 收入/支出. Resolve the sign question before writing code.
2. **Write `AlipayAdapter.parse()`** with the column reads above. Commit.
3. **Write `test_alipay_adapter.py`** unit tests. Iterate until green. Commit.
4. **End-to-end verification.** Run `test_csv_parser_fixtures.py[alipay]` — must pass byte-exact. If it fails, fix the adapter; never the fixture. Commit.
5. **Delivery notes.** Confirm the legacy Alipay path is no longer exercised by production (adapter registration routes to new pipeline).

## Definition of Done

- All Acceptance Criteria met.
- The Task 0 Alipay fixture is now the regression oracle for the new pipeline, not the legacy one.
- Wells Fargo and ICBC still pass (Wells Fargo through Task 02 adapter; ICBC through legacy fallback).

## Dependencies

- **Depends on Task 01** (intermediate writer) and **Task 02** (dispatch seam + `generic.checking` translator). Without the seam, registering the adapter has no runtime effect; the legacy path still wins.
- **Concurrent with Task 05** — no file overlap.

## Out of Scope

- ICBC adapter (Task 05).
- Multi-currency Alipay support (no fixture data; future adapter extension if Alipay ever introduces USD rows for a user).
- Preserving 备注 column as note metadata (legacy drops it; byte-exact compatibility requires this adapter to drop it too).
- Changes to GB18030 encoding handling — `csv_normalizer.py` owns that.
