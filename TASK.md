# Task 01 — Intermediate CSV Writer

## Title

Serialize `LedgerTransaction` streams into the project's intermediate CSV format byte-exact.

## Objective

Add the serializer that Tasks 02, 04, and 05 will chain onto (adapter → translator → **writer** → bytes). The writer's output must match today's `normalize_csv_to_intermediate()` output byte-for-byte on every Task 0 golden fixture, so the SHA-256 import-identity hashes do not drift when Tasks 02+ start routing real CSVs through the new pipeline.

This task is not user-visible. Its value is that every subsequent task has a deterministic byte-level target.

## Context

Task 0 shipped golden fixtures for Wells Fargo, Alipay, and ICBC at `app/backend/tests/fixtures/csv_snapshots/<institution>/{input,expected_intermediate}.csv` and the end-to-end parameterized test `app/backend/tests/test_csv_parser_fixtures.py`. The fixtures are byte-exact records of what today's `normalize_csv_to_intermediate()` produces. This task must be able to reproduce those bytes starting from a synthesized `LedgerTransaction` stream.

## Scope

### Included

**Extend `app/backend/services/parsers/types.py`:**

- `Record`: add `balance: Decimal | None = None` and `note: str | None = None` below the existing fields. Aggregator-neutral; CSV adapters populate these when the source CSV exposes a running-balance column and a free-text note column. Leave unchanged otherwise.
- `LedgerTransaction`: add `balance: Decimal | None = None` (mirrors the running balance of the primary tracked-account posting at the time of this transaction).
- `Posting`: no changes.
- `Adapter` / `Translator` protocols: no changes.

**New file `app/backend/services/parsers/intermediate_writer.py`:**

```python
from __future__ import annotations
from collections.abc import Iterable, Sequence
from io import StringIO

from .types import LedgerTransaction

INTERMEDIATE_FIELDNAMES: tuple[str, ...] = (
    "date", "code", "description", "amount", "total", "note",
)


def write_intermediate(
    transactions: Iterable[LedgerTransaction],
    *,
    fieldnames: Sequence[str] = INTERMEDIATE_FIELDNAMES,
) -> str:
    """Serialize LedgerTransactions to the project's intermediate CSV format.

    Contract:
    - Ordering: writes transactions in the order received. Callers that need
      newest-first ordering (the legacy convention) reverse before passing.
    - Line endings: CRLF (Python csv.DictWriter default in text mode).
    - Encoding: returns str; caller encodes to UTF-8 if bytes are needed.
    - Columns: writes exactly `fieldnames` as the header row; LedgerTransactions
      that carry fields outside this list have them dropped.
    - Amount/total formatting: see module docstring.
    """
```

Formatting rules the writer implements (these mirror the behavior of today's `BankCSV.amount()`, `BankCSV.total()`, and `BankCSV.currency()` across the shipped fixtures):

- **Primary-posting selection.** For each `LedgerTransaction`, the posting whose `account` equals the translator's tracked-account argument is the primary posting; the writer renders its `amount` as the `amount` column. If a translator emits `LedgerTransaction.postings[0]` as the tracked-account posting by convention, the writer can rely on that — document the convention and enforce it in the translator tests.
- **Amount cell.** `{commodity}{amount:.2f}` when `len(commodity) == 1` (e.g., `$-1000.00`). `{amount:.2f}{commodity}` when `len(commodity) > 1` (e.g., `-9.90CNY`, `-12.34USD`). Sign is preserved; negative numbers render as `$-1000.00`, not `-$1000.00`, to match the current fixtures.
- **Total cell.** Formatted the same way as amount BUT uses thousand separators: `{commodity}{balance:,.2f}` or `{balance:,.2f}{commodity}`. If `LedgerTransaction.balance` is `None`, the cell is emitted empty (this is the Wells Fargo case; the WF fixture has empty totals throughout).
- **Date cell.** `YYYY/MM/DD` (forward slashes). Matches `LedgerTransaction.date.strftime("%Y/%m/%d")`.
- **Code cell.** `LedgerTransaction.code` or empty string if `None`.
- **Description cell.** `LedgerTransaction.payee`. No prefix, no trimming.
- **Note cell.** `LedgerTransaction.note` or empty string if `None`.

The `:f` vs `:,f` split (amount no thousand sep, total with thousand sep) is a historical quirk inherited from `BankCSV.amount()` vs `BankCSV.total()`. Capture it in comments tied to the specific fixtures it reproduces; post-refactor normalization is out of scope for this task.

**New file `app/backend/tests/test_intermediate_writer.py`:**

Unit tests covering:

- Empty iterable → single header row with CRLF terminator.
- Single transaction with 1-char commodity (`"$"`) and positive amount, negative amount, amount with cents → matches literal byte string.
- Single transaction with multi-char commodity (`"CNY"`, `"USD"`) → suffix format matches literal byte string.
- Transaction with `balance=None` → empty total cell.
- Transaction with `balance` that crosses the thousand mark → comma-separated total, properly CSV-quoted because of the embedded comma.
- Multiple transactions → ordering preserved (no reversal by the writer).
- Transaction with `note=None` → empty note cell; transaction with `note="CHECK # 281"` → literal note cell.

Each test asserts `write_intermediate(...).encode("utf-8") == b"<literal>"`. Byte-level, not string-level.

### Explicitly excluded

- No adapter or translator implementations. This task ships the writer alone.
- No wiring into `csv_normalizer.py` — the legacy pipeline keeps running unchanged. Task 02 adds the dispatch seam.
- No commodity-style postings (stocks, securities). The `Posting.price` / `Posting.commodity` round-trip for multi-commodity transactions is out of scope; Schwab is being deleted in Task 07.
- No modifications to the existing `test_csv_parser_fixtures.py` — the end-to-end oracle is unchanged and untouched.
- No changes to `csv_normalizer.py`, `custom_csv_service.py`, `institution_registry.py`, `Scripts/BankCSV.py`, or any route handler.
- No support for variable `fieldnames` beyond the default tuple — the `fieldnames` parameter exists for future use (Schwab-style `symbol`/`price` columns) but is not exercised in tests.

## System Behavior

**Inputs:** an `Iterable[LedgerTransaction]` from a caller (translator output).

**Logic:** for each transaction, build a `dict` keyed by `INTERMEDIATE_FIELDNAMES`, applying the formatting rules above. Feed through `csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")`. `out` is a `StringIO`. Return `out.getvalue()`.

**Outputs:** a `str` containing the full CSV document (header + rows), CRLF-terminated, UTF-8-safe (only ASCII + whatever characters the payee/note text carries).

## System Invariants

- The intermediate CSV format is a byte-exact regression target. Any change to the writer's output format invalidates every previously imported transaction's `source_identity` hash. This task's entire reason to exist is preserving that invariant.
- The writer does not know about institutions or account configs. It consumes only `LedgerTransaction`. All institution-specific knowledge lives upstream (adapter, translator).
- No file I/O. The writer returns a string; the caller writes to disk or stdin if needed.
- No dependency on the legacy `Scripts/BankCSV.py`. The writer is self-contained.
- `LedgerTransaction.postings` can have any length ≥ 2. The writer only renders the primary posting's amount; additional postings (the other side of the double-entry, opening-balance stubs, fee splits) are not visible in the intermediate CSV — they are synthesized later by `ledger convert`.

## States

Not applicable — no UI, no runtime state.

## Edge Cases

- **`LedgerTransaction.balance == None`.** Emit empty total cell. (Wells Fargo fixture exercise.)
- **Balance crosses thousand boundary.** Emit with comma thousand separator; csv.DictWriter auto-quotes cells containing commas, matching ICBC fixture's `"2,568.44CNY"`.
- **Commodity is a 1-char symbol like `"$"`.** Prefix format.
- **Commodity is a 3-letter ISO code like `"USD"` or `"CNY"`.** Suffix format.
- **Commodity is an empty string or `None`.** Not expected from a well-formed translator. Fail loudly (raise `ValueError`) rather than emit ambiguous output.
- **Amount has more than 2 decimal places.** `:.2f` rounds to 2 — matches legacy. If the source CSV has sub-cent precision, legacy drops it; writer does the same.
- **Negative balance.** Renders as `$-2,568.44` or `-2,568.44CNY`. Sign handled identically to amount.
- **Empty description (payee).** Emit empty cell. Not synthesized.

## Failure Behavior

- **Empty commodity.** Raise `ValueError("LedgerTransaction posting commodity is required")`. Translator bugs must surface loudly.
- **Primary-posting amount is `None`.** Raise `ValueError("Primary posting amount is required")`. Same rationale.
- **Non-`Decimal` amount.** Raise `TypeError`. Do not silently coerce — translator must emit `Decimal`.
- **Caller passes a wrong `fieldnames` that omits required columns like `"amount"`.** Let `csv.DictWriter` raise whatever it raises — no custom validation beyond what the stdlib provides.

## Regression Risks

- **Drift from legacy byte output.** The only honest verification is running the writer against real fixtures end-to-end (Task 02 starts doing this). This task's tests exercise the formatting rules in isolation; they cannot prove byte-exactness against real CSVs by themselves. Mitigation: the unit tests use byte strings derived from literal excerpts of the Task 0 fixtures (pull 2–3 rows from each fixture, hand-construct the LedgerTransaction that produces them, assert the writer emits those exact bytes).
- **Accidental UTF-8 BOM.** `StringIO` + `csv.DictWriter` does not add a BOM; writing `out.getvalue().encode("utf-8")` produces BOM-less bytes. Verify in the tests.
- **CRLF vs LF line endings.** `csv.DictWriter` uses CRLF by default when given a text-mode StringIO. Verify with `\r\n` checks in the tests; do not open the StringIO with `newline=""` — that would drop the CRLF conversion.
- **Thousand-separator inconsistency.** Rule is: amount no thousand sep, total thousand sep. Easy to invert. Tests must cover both.
- **Breaking Task 0's test.** The parameterized test still routes through the legacy `normalize_csv_to_intermediate()` in this task. It must stay green. Do not touch `test_csv_parser_fixtures.py`.
- **Regression in `types.py`.** Adding fields to `Record` and `LedgerTransaction` is additive; no existing consumer reads the new fields. Verify: `grep -rE "Record\(|LedgerTransaction\(" app/backend/` returns no call sites outside `types.py` (Task 0 did not introduce any).

## Acceptance Criteria

- `Record.balance: Decimal | None = None`, `Record.note: str | None = None`, `LedgerTransaction.balance: Decimal | None = None` all importable from `app.backend.services.parsers.types`.
- `write_intermediate` and `INTERMEDIATE_FIELDNAMES` importable from `app.backend.services.parsers.intermediate_writer`.
- `uv run python -c "from app.backend.services.parsers.intermediate_writer import write_intermediate; print(write_intermediate([]))"` prints exactly `date,code,description,amount,total,note\r\n` (with a literal CRLF).
- `uv run pytest app/backend/tests/test_intermediate_writer.py -q` is green.
- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q` is still green (unchanged; legacy pipeline still owns it).
- `grep -rE "from .*intermediate_writer|import intermediate_writer" app/backend/` returns hits only in this task's own test file (the writer is not yet wired into the runtime).
- `git diff --stat HEAD~N -- 'app/backend/services/' ':!app/backend/services/parsers/'` shows zero files modified outside `services/parsers/`.
- `git diff --stat HEAD~N -- Scripts/` shows zero changes.

## Proposed Sequence

1. **Extend `types.py`.** Add the three fields. Verify `uv run python -c "from app.backend.services.parsers.types import Record, LedgerTransaction; Record(date=..., description='x'); LedgerTransaction(date=..., payee='x', postings=[])"` constructs cleanly with defaults. Commit.
2. **Draft `intermediate_writer.py`** with the formatting rules and docstring. Commit.
3. **Write `test_intermediate_writer.py`** with byte-literal assertions for the edge cases listed above. Iterate until green. Commit.
4. **Cross-check against Task 0 fixtures.** For Wells Fargo, hand-construct 2–3 `LedgerTransaction` instances from the first 2–3 rows of `wells_fargo/expected_intermediate.csv` and assert the writer reproduces those rows. Same for Alipay and ICBC (cover both prefix and suffix commodities). Add these as part of `test_intermediate_writer.py`. Commit.
5. **Verify zero integration.** Run the `grep` and `git diff --stat` commands from Acceptance Criteria. Commit any needed delivery notes.

Commit granularity: one commit for types.py; one commit for the writer module; one commit for the tests; one commit for the fixture-cross-check tests. Bisect-friendly.

## Definition of Done

- All Acceptance Criteria met.
- Byte-exact reproduction verified against at least three fixture excerpts (WF, Alipay, ICBC).
- No file outside `app/backend/services/parsers/` or `app/backend/tests/` modified.
- `types.py` changes are purely additive; no existing field renamed or repositioned.
- `test_csv_parser_fixtures.py` still green.

## Dependencies

None — this task lands on master directly.

## Out of Scope

- Adapter and translator implementations (Tasks 02, 04, 05).
- Dispatch seam wiring in `csv_normalizer.py` (Task 02).
- Commodity/price support (stocks, securities; Schwab is going away in Task 07).
- Any `Record` or `LedgerTransaction` field beyond the three listed.
- Normalizing the amount-vs-total formatting inconsistency (thousand sep on one, not the other) — this is a legacy quirk the writer reproduces; cleanup is post-Task 07.
