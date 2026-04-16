# Task 05 — ICBC Adapter

## Title

Port `IcbcCSV` (Scripts/BankCSV.py:167-211) to `services/parsers/implementations/icbc.py`, reusing `generic.checking` translator. Route ICBC imports through the new pipeline.

## Objective

After this task, `normalize_csv_to_intermediate()` for ICBC CSVs produces byte-exact the same intermediate CSV as before, verified by `test_csv_parser_fixtures.py[icbc]` running end-to-end through the new adapter.

## Context

ICBC CSVs arrive as UTF-8 text (BOM present) with a 7-row preamble and 2-row footer. `csv_normalizer.py` owns decoding and slicing (Option B); the adapter receives already-decoded, already-sliced text.

Reference implementation: `Scripts/BankCSV.py:167-211`. Golden fixture: `app/backend/tests/fixtures/csv_snapshots/icbc/{input,expected_intermediate}.csv`.

Key ICBC-specific complexity:

- **Mixed currency.** `IcbcCSV.currency(row)` reads 记账币种: `美元` → `"USD"`, anything else → `"CNY"`. Record.currency is set per-row.
- **Debit/credit split columns.** 记账金额(收入) and 记账金额(支出) are separate unsigned columns; `IcbcCSV.amount()` prepends `-` for expense rows (unlike Alipay where the source carries signs).
- **Description is compound.** `IcbcCSV.description(row)` concatenates `row["交易场所"].strip() + " " + row["对方户名"].strip()`. Adapter must reproduce this exactly.
- **Code is `摘要`** (summary / transaction type), not an ID. E.g., `消费`, `退款`.
- **Balance uses current-row currency** — `IcbcCSV.total()` returns `row["余额"].strip() + currency` where `currency` is the per-row result of `IcbcCSV.currency(row)`.

The Task 0 ICBC fixture contains 6 body rows: 1 USD expense (synthesized to exercise the 美元 branch), 4 CNY expense, 1 CNY income. Byte-exact output from the Task 0 snapshot (`expected_intermediate.csv`):

```
2025/01/01,消费,支付宝-PAYEE_005 PAYEE_005,-9.90CNY,"2,568.44CNY",
2025/01/04,消费,PAYEE_USD_001 PAYEE_USD_001,-12.34USD,500.00USD,
```

Amount: no thousand separator. Total: thousand separator for values crossing 1000. Currency is suffixed (multi-char code `USD`/`CNY` — triggers the writer's suffix format rule).

## Scope

### Included

**New file `app/backend/services/parsers/implementations/icbc.py`:**

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
class IcbcAdapter:
    name = "icbc"
    institution = "icbc"
    formats = ("csv",)
    translator_name = "generic.checking"

    def parse(self, text: str) -> Iterator[Record]:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            currency = self._currency(row)
            amtout = row["记账金额(支出)"].strip()
            amtin = row["记账金额(收入)"].strip()

            if amtout:
                amount = -Decimal(amtout)
            elif amtin:
                amount = Decimal(amtin)
            else:
                amount = None

            yield Record(
                date=datetime.strptime(row["交易日期"].strip(), "%Y-%m-%d").date(),
                description=(row["交易场所"].strip() + " " + row["对方户名"].strip()).strip(),
                amount=amount,
                currency=currency,
                code=row["摘要"].strip() or None,
                counterparty=row["对方户名"].strip() or None,
                balance=Decimal(row["余额"].strip()) if row.get("余额", "").strip() else None,
                note=None,  # IcbcCSV does not override BankCSV.note(); always None.
                raw={k: v for k, v in row.items() if v},
            )

    @staticmethod
    def _currency(row) -> str:
        # Mirrors Scripts/BankCSV.py:196-198.
        return "USD" if row.get("记账币种", "").strip() == "美元" else "CNY"
```

Column names to read (must match `IcbcCSV.__init__` at `Scripts/BankCSV.py:172-188`): `交易日期`, `摘要`, `交易详情`, `交易场所`, `交易国家或地区简称`, `钞/汇`, `交易金额(收入)`, `交易金额(支出)`, `交易币种`, `记账金额(收入)`, `记账金额(支出)`, `记账币种`, `余额`, `对方户名`, `对方账户`.

**New file `app/backend/tests/test_icbc_adapter.py`:**

- Adapter-level unit tests using literal UTF-8 CSV text excerpts:
  - CNY expense row → `Record(amount=-9.90, currency="CNY")`.
  - USD expense row → `Record(amount=-12.34, currency="USD")`.
  - CNY income row → `Record(amount=25.00, currency="CNY")`.
  - Row with empty 交易场所 → description is just `对方户名` (stripped to remove leading space).
  - Row with empty 对方户名 → description is just `交易场所`.
  - Row where `记账币种` is neither 美元 nor empty — falls through to CNY per legacy logic.
- End-to-end test: call `normalize_csv_to_intermediate()` with the Task 0 ICBC fixture; assert byte-exact equality.

**No modification to `test_csv_parser_fixtures.py`:** existing parameterized test covers ICBC via the dispatch seam.

**No modification to `csv_normalizer.py`:** the Task 02 seam routes by institution slug.

### Explicitly excluded

- No fixture changes (Task 0 shipped the ICBC fixture).
- No `Scripts/BankCSV.py` changes (IcbcCSV stays until Task 07).
- No `institution_registry.py` changes (Task 06b).
- No new translator.
- No frontend, API, or config changes.

## System Behavior

**Inputs:** pre-decoded UTF-8 text (with BOM handled by Python's csv reader), header intact, preamble/footer already sliced.

**Logic:** DictReader → per-row currency detection → amount sign from split columns → Record emission.

**Outputs:** `Iterator[Record]`.

## System Invariants

- Record emission order matches source CSV row order.
- `Record.currency` varies per row (`"CNY"` or `"USD"`).
- `Record.note` is always `None` (legacy behavior).
- `IcbcAdapter.translator_name == "generic.checking"`.
- The Task 0 ICBC fixture continues to pass byte-exact.

## States

Not applicable.

## Edge Cases

- **Both 记账金额(收入) and 记账金额(支出) empty.** Adapter emits `Record.amount = None`. Writer raises `ValueError`. Legacy `IcbcCSV.amount()` returns `None` in this branch; the legacy path would emit an empty amount cell. Behavioral divergence — verify fixture has no such rows before shipping, else add a passthrough branch.
- **Both populated (unexpected).** Legacy returns the expense branch first (`if amtout:`). Adapter matches.
- **BOM in 交易日期 after dict-read.** If the CSV has a BOM and DictReader exposes it in the first field name as `\ufeff交易日期`, `row["交易日期"]` raises `KeyError`. Verify DictReader's default behavior on the fixture; if needed, normalize by decoding with `encoding="utf-8-sig"` before `csv_normalizer.py` splits lines — but this is `csv_normalizer.py`'s concern, not this adapter's. If the fixture test fails with a KeyError, escalate to Task 02's contract.
- **记账币种 contains something other than `美元` or CNY-typical.** Legacy falls through to CNY per `"USD" if currency == "美元" else "CNY"`. Adapter matches.
- **余额 empty.** Adapter emits `Record.balance = None`. Writer emits empty total cell.

## Failure Behavior

- **Malformed date.** Propagate `ValueError`.
- **Non-numeric amount string.** Propagate `decimal.InvalidOperation`.
- **Missing required column.** Propagate `KeyError`.
- **Byte-exact fixture test fails.** Fix the adapter. Do not touch the fixture.

## Regression Risks

- **Currency detection mismatch.** Verify the synthesized USD row in the Task 0 fixture reads `美元` literally in `记账币种`. If the fixture's synthesized USD row uses a different marker (e.g., `USD`), the adapter's 美元-only check misses it. Fix by extending the check to include the actual marker.
- **Description concatenation whitespace.** `交易场所.strip() + " " + 对方户名.strip()` leaves a leading or trailing space if one side is empty — legacy does not trim the final result. Adapter wraps with `.strip()` to prevent leading/trailing space; verify byte-exact against fixture rows that have one side empty. If legacy emits `" PAYEE_005"` (leading space) rather than `"PAYEE_005"`, the adapter must match.
- **Balance currency suffix in legacy vs. new.** Legacy `IcbcCSV.total()` appends currency directly. New pipeline carries balance as `Decimal`; writer applies currency from Record.currency. Must produce identical bytes for both USD and CNY rows.
- **Thousand-separator inconsistency.** Writer rule from Task 01: `{amount:.2f}` (no thousand sep) for amount, `{balance:,.2f}` (thousand sep) for total. Fixture confirms: `-9.90CNY` vs `"2,568.44CNY"`. If real-world data shows thousand-sep on amount or no-thousand-sep on total, the writer's rule is wrong and Task 01 needs a patch — escalate.
- **Registration conflict.** `"icbc"` adapter name is unique in Wave 3 (no sibling uses it).

## Acceptance Criteria

- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q` is green (all three institutions).
- `uv run pytest app/backend/tests/test_icbc_adapter.py -q` is green.
- `uv run python -c "from app.backend.services.parsers import registry; registry.discover(); a = registry.get_adapter('icbc'); print(a.translator_name, a.institution)"` prints `generic.checking icbc`.
- `Scripts/BankCSV.py` byte-identical.
- `git diff --stat` shows: `implementations/icbc.py` added; `tests/test_icbc_adapter.py` added. No other files.

## Proposed Sequence

1. **Read `Scripts/BankCSV.py:167-211`** and the Task 0 ICBC fixture's `input.csv`. Confirm the 美元 currency marker is literally present in the synthesized USD row.
2. **Write `IcbcAdapter.parse()`.** Commit.
3. **Write `test_icbc_adapter.py`** with all currency and sign branches covered. Commit.
4. **End-to-end verification.** `test_csv_parser_fixtures.py[icbc]` must pass byte-exact. Commit.

## Definition of Done

- All Acceptance Criteria met.
- ICBC now uses the new pipeline end-to-end.
- Wells Fargo (Task 02), Alipay (Task 04), and ICBC (this task) all pass byte-exact through the new pipeline; Schwab and BJB remain on the legacy fallback until Task 07 deletes both.

## Dependencies

- **Task 01** (intermediate writer) and **Task 02** (dispatch seam + `generic.checking`).
- **Concurrent with Task 04** — no file overlap.

## Out of Scope

- BJB adapter — cut as YAGNI (2026-04-15 scope trim); BJB is removed from `institution_registry` in Task 07.
- ICBC brokerage / investment rows (not present in the fixture; assume cash-only).
- Normalization of the amount vs. total thousand-separator inconsistency — preserved byte-exact for now.
- Handling other Chinese banks' 美元 representations. Task 05 covers ICBC only.
