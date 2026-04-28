# Date Format Standardization — ISO 8601 (`YYYY-MM-DD`) (8a-fix)

## Objective

Adopt ISO 8601 (`YYYY-MM-DD`) as the project's single canonical date format across journal files, ledger CLI invocations, and any code path that string-compares journal dates. Eliminate ledger's default `YYYY/MM/DD` rendering by setting `LEDGER_DATE_FORMAT` in the runner. Migrate the existing workspace journal files to ISO. Document the choice. This unblocks 8a's `_insertion_index_for_date` logic, which assumes ISO and silently mis-inserts assertions into journals using slash dates (the bug surfaced during 8b manual testing of credit-card reconciliation: assertion landed at the top of the file rather than after `periodEnd`'s last transaction).

## Scope

### Included

1. **`LEDGER_DATE_FORMAT="%Y-%m-%d"` set in the ledger runner's environment.** Modify `app/backend/services/ledger_runner.py:run_cmd` to merge `{"LEDGER_DATE_FORMAT": "%Y-%m-%d"}` into the subprocess env (preserving the inherited environment). Every existing call site (`reconciliation_service.verify_assertion`, `reconciliation_service.reconciliation_status`, `import_service`, anywhere else `run_cmd` is invoked) inherits the setting automatically.
2. **Journal migration script** at `Scripts/migrate_journal_dates_to_iso.py`. Scans `workspace/journals/*.journal` and `workspace/opening/*.journal` (excluding `*.bak.*` files). Replaces transaction header dates `^(\d{4})/(\d{2})/(\d{2})\s` with `^\1-\2-\3\s`. Leaves metadata comments (lines starting with `;`) untouched — those carry verbatim CSV strings from banks, not ledger-significant dates. Idempotent: re-running on an already-ISO journal is a no-op. The script writes a backup file (`<name>.iso-migration.bak.<timestamp>`) for each modified journal before mutating, matching the repo's existing backup convention.
3. **Run the migration** against the live workspace as part of this task. The journals at `workspace/journals/2026.journal` and `workspace/opening/*.journal` end the task in ISO format. Existing `*.bak.*` files stay slash-formatted as historical record.
4. **Audit all journal-writer code paths** for date format consistency. The known writers and helpers:
   - `reconciliation_service.write_assertion_transaction` (already uses `period_end.isoformat()` — verify).
   - `manual_entry_service` (manual transaction creation).
   - `import_service` (CSV import path that writes new transactions).
   - `transactions_create` and any other endpoint in `main.py` that appends to a journal.
   - Any helper in `transaction_helpers.py` or `journal_query_service.py` that formats a date.
   Each must emit `date.isoformat()` (ISO) for transaction header lines, never `strftime('%Y/%m/%d')`. Add a unit test per writer that asserts the produced header line matches `^\d{4}-\d{2}-\d{2}\s`.
5. **`DECISIONS.md` §20** — new section codifying the standard. Title: "Journal dates are ISO 8601." Body: ledger's default `YYYY/MM/DD` is overridden via `LEDGER_DATE_FORMAT="%Y-%m-%d"` in the runner; the writer emits ISO; the migration is a one-shot pass committed alongside this task. Future writers must emit ISO. Ledger's input parser tolerates both formats by default, so reading legacy slash dates still works if a user imports a journal from elsewhere — but our writers must not produce slash output.
6. **Regression test** at `app/backend/tests/test_journal_date_format.py`. Scans test fixtures (not user data) for compliance: any `.journal` file under `app/backend/tests/fixtures/` whose transaction headers contain `^\d{4}/\d{2}/\d{2}` triggers a failing assertion. Also asserts that `run_cmd` invocations include `LEDGER_DATE_FORMAT="%Y-%m-%d"` in their env (mock-based or via a fixture that wraps `subprocess.run`).
7. **Update existing test fixtures** that use slash-format dates (none found in the current test suite per the 8a/8b ISO bias, but the audit confirms it).

### Explicitly Excluded

- Restoring slash-format support in any writer. The runner's `LEDGER_DATE_FORMAT` plus the migration make slash-format an external-only concern; we never produce it.
- Setting `LEDGER_INPUT_DATE_FORMAT`. Ledger's default parser handles both formats and we want imported third-party journals to still parse without configuration.
- Migrating `.bak.*` backup files. They're historical records.
- Migrating CSV metadata comments inside transactions (`; CSV: 2026/01/01,...`). Those are verbatim from the bank and not ledger-significant.
- Any change to user-facing date display in the frontend. Frontend dates are formatted via `formatCurrency`/locale-aware helpers and don't share the ledger journal's representation.
- Smart-date offsets, multi-currency, or any other 8c/8d/8e/8h work.
- Reopening 8a's wider design (the assertion writer, the event log, the import fence). Those stay shipped; this task only fixes the date-format assumption.

## System Behavior

### Inputs / Triggers

- Any code path that calls `ledger` via `run_cmd` runs with `LEDGER_DATE_FORMAT="%Y-%m-%d"` in its environment.
- Any journal-writer code path emits transaction header dates in ISO format.
- The migration script runs once during this task's delivery to bring existing journals to ISO.

### Logic

- `run_cmd` builds an `env` dict by copying `os.environ` and overlaying `{"LEDGER_DATE_FORMAT": "%Y-%m-%d"}`, then passes `env=env` to `subprocess.run`. Inheriting `os.environ` preserves `PATH`, `HOME`, etc.
- The migration script iterates target files, reads each, applies `re.sub(r'^(\d{4})/(\d{2})/(\d{2})(\s)', r'\1-\2-\3\4', text, flags=re.MULTILINE)`, writes back if changed. Tracks modifications and prints a summary.
- The regression test fails closed: any fixture or runtime call that drifts back to slash format breaks the build.

### Outputs

- Migrated journals: `workspace/journals/2026.journal` and `workspace/opening/*.journal` use ISO header dates. Their `*.bak` backups created by the migration script preserve the pre-migration state.
- `DECISIONS.md` gains §20.
- All ledger CLI invocations from this codebase emit ISO dates in their output.
- 8a's `_insertion_index_for_date` now functions correctly: `block_date = line[:10]` matches `target_date = period_end.isoformat()` because both are ISO.

## System Invariants

- Every journal file written by Ledger Flow uses ISO date format on transaction headers. No exceptions.
- `run_cmd` always sets `LEDGER_DATE_FORMAT="%Y-%m-%d"` regardless of caller. Single chokepoint, no per-call overrides.
- Ledger's input parser still tolerates slash format (so externally-sourced slash-formatted journals can be read), but our code never produces slash output.
- `_insertion_index_for_date` and any future date-prefix string comparison in the codebase assume ISO and require it (enforced by writer invariant + migration).
- The migration script is idempotent: running it twice produces the same output as running it once.

## States

- **Pre-migration:** journals contain slash-formatted headers; `_insertion_index_for_date` mis-inserts assertions; `LEDGER_DATE_FORMAT` unset; ledger renders `2026/01/18` in error messages.
- **Post-migration:** journals are ISO-formatted; `LEDGER_DATE_FORMAT="%Y-%m-%d"` set in the runner env; ledger renders `2026-01-18` in error messages; the writer's matching logic works.
- **Mid-migration (transient):** the migration script's atomicity is per-file. If interrupted mid-run, some journals are migrated and some are not. Either state is internally consistent (each file is well-formed); a re-run completes the rest.

## Edge Cases

- **A journal that is already fully ISO.** Migration script is a no-op for that file (no replacements applied → no backup created → no rewrite).
- **A journal with mixed formats** (some slash, some ISO — possible if a user hand-edited or imported partially). The script normalizes all matching transaction headers to ISO; metadata comments untouched.
- **A backup file that looks like a live journal** (`workspace/journals/2026.journal.import.bak.20260326225645`). Excluded by the script's `.bak.` filename filter.
- **A journal entry whose date is mid-line** (e.g., `; CSV: 2026/01/01,...,...`). Anchored regex (`^(\d{4})/...`) only matches start of line, so metadata comments are safe.
- **`LEDGER_DATE_FORMAT` is already set in the user's shell** to a non-ISO value. Our `env` overlay overrides it for our subprocess only — the user's shell env is unaffected after the call returns.
- **External tools called by ledger that read `LEDGER_DATE_FORMAT`.** Ledger itself respects it; price databases or other helpers might too. Setting it project-wide for our subprocess is the safe behavior.
- **An existing test fixture journal under `app/backend/tests/fixtures/` uses slash format.** Audit + correct as part of this task; the regression test prevents future drift.

## Failure Behavior

- Migration script encounters a malformed journal (parser error): print the file name and the offending line, skip the file, exit non-zero. Do not write a partial migration. The user can fix the journal manually and re-run.
- `run_cmd` env overlay fails (e.g., `os.environ` raises): propagate the exception. This is a fundamental failure that should not be silently swallowed.
- Regression test discovers slash-formatted fixtures: fails the build with a list of offending files. The dev fixes the fixtures.
- Ledger CLI doesn't respect `LEDGER_DATE_FORMAT` for some reason (very old version): manifests as ledger emitting slash dates in error messages, which our parser would still tolerate (the parser doesn't depend on format) — so the user-facing impact is limited to the cosmetic "found $X" string format. Document the minimum supported ledger version in DECISIONS §20.

## Regression Risks

- **Backup files filtered incorrectly.** The migration script must not touch any `*.bak.*` file. Verify by listing the directory before and after the migration: backup files unchanged, modification timestamps unchanged.
- **Mid-line slash-formatted dates touched accidentally.** Anchor the regex with `^` and `re.MULTILINE`. Test with a journal containing `; CSV: 2026/01/01,...` — that line must be unchanged.
- **Subprocess env override breaks `PATH` or other inherited variables.** `env` defaults to `os.environ` when not provided; we must build a copy and overlay, not pass only `{"LEDGER_DATE_FORMAT": ...}`. Test `run_cmd` with a subprocess that prints `os.environ.get("PATH")` and verify PATH is intact.
- **`reconciliation_service.write_assertion_transaction` already uses `isoformat()`.** Confirm explicitly during the audit; if a regression found slash output anywhere, the writer's contract is broken.
- **Existing 8a tests passing on synthetic ISO fixtures missed this bug entirely.** That's a fixture-realism gap caught by the recent skill updates; this task fixes the *symptom*, the skill edits prevent recurrence.
- **The migration runs on the user's live workspace.** Backup-before-write is the safety net. Verify by inspecting the backup file content matches the pre-migration state.

## Acceptance Criteria

- `app/backend/services/ledger_runner.py:run_cmd` builds an env dict from `os.environ` overlaid with `{"LEDGER_DATE_FORMAT": "%Y-%m-%d"}` and passes it via `env=` to `subprocess.run`.
- A unit test asserts that `run_cmd` calls `subprocess.run` with `env["LEDGER_DATE_FORMAT"] == "%Y-%m-%d"` and that other inherited variables (e.g., `PATH`) are preserved.
- `Scripts/migrate_journal_dates_to_iso.py` exists, is idempotent, processes `workspace/journals/*.journal` and `workspace/opening/*.journal` excluding `*.bak.*`, writes per-file backups before mutating, and prints a summary.
- After running the migration, every transaction header in `workspace/journals/2026.journal` and `workspace/opening/*.journal` matches `^\d{4}-\d{2}-\d{2}\s`. Backup files remain unchanged.
- `DECISIONS.md §20` documents the ISO standard, the env-var mechanism, and the migration.
- `app/backend/tests/test_journal_date_format.py` scans `app/backend/tests/fixtures/**/*.journal` for slash-formatted headers and fails if any are found.
- All journal-writer code paths emit ISO dates. A unit test per writer asserts the produced header line matches `^\d{4}-\d{2}-\d{2}\s`.
- Existing 8a/8b reconciliation tests continue to pass.
- Manual end-to-end probe: against the migrated workspace, opening the reconcile modal on Wells Fargo Credit Card, picking a known closing balance for an actual statement period (e.g., the $-1,491.71 case from the 8b bug report), and clicking Reconcile produces a successful reconciliation. The assertion transaction inserts after the last transaction with date `periodEnd` in `2026.journal`. Ledger verifies it. The event is emitted.
- `pnpm check` passes (no frontend changes expected, but the shape is unchanged so this is a free check).
- `uv run pytest -q` passes.

## Proposed Sequence

1. **Runner env overlay.** Modify `run_cmd` to set `LEDGER_DATE_FORMAT="%Y-%m-%d"`. Add the unit test. Verify the existing 8a/8b suite still passes — ledger error messages now arrive with ISO dates, but our parser doesn't depend on format. **Verifiable in isolation.**
2. **Writer audit.** Read every journal-write site and verify it uses `isoformat()`. Add a per-writer test that asserts the produced header is ISO. Fix any drift found. **Verifiable in isolation.**
3. **Migration script.** Write `Scripts/migrate_journal_dates_to_iso.py`. Test it against a temp copy of one slash-formatted journal. Verify idempotence by running twice. **Verifiable in isolation.**
4. **Run the migration on the live workspace.** Commit the script's run output (the migrated journals + the backup files it creates) so the repo state matches what the user is running locally. The dev should NOT run this against unrelated state — confirm with the user before pushing if any backup file gets generated for a file the user didn't expect.
5. **Regression test.** Add `test_journal_date_format.py` that scans test fixtures.
6. **`DECISIONS.md §20`** entry.
7. **Manual end-to-end probe** with the modal: trigger the reconciliation, confirm it succeeds. This is the QA-skill-mandated real-data probe.

## Definition of Done

- All acceptance criteria pass.
- `uv run pytest -q` passes (existing suite + new tests).
- `pnpm check` passes.
- Migration completed on the live workspace; backup files preserved.
- `DECISIONS.md §20` lands.
- The 8b reconciliation flow (Wells Fargo Credit Card scenario) works end-to-end against the migrated workspace.
- A short follow-up note appended to `plans/statement-reconciliation.md` recording that 8a's "last on its date" invariant was always ISO-dependent, that this task makes the dependency explicit, and that the bug was caught during 8b's first real-data probe.
- ROADMAP.md gains a one-line note that 8a-fix shipped (this task) — no roadmap reordering, 8c remains the active focus.

## Out of Scope

- All items under "Explicitly Excluded" above.
- Any change to the assertion writer's logic itself (`_insertion_index_for_date`, `_splice_block`, etc.). The bug is environmental; the code is correct given the ISO precondition.
- Frontend display changes.
- Other 8-series sub-features.

## Dependencies

- 8a (backend) — shipped. The writer's correctness depends on ISO journals (now enforced).
- 8b (modal) — shipped. The modal does not depend on date format directly; it uses ISO via the API contract.
- The `ledger` CLI must respect `LEDGER_DATE_FORMAT`. All maintained ledger versions (≥3.x) do.

## Open Questions

None. Decisions inline:

- **Env var, not CLI flag.** One place to set, applies to every CLI invocation. No risk of forgetting to pass `--date-format` on a new call site.
- **Don't set `LEDGER_INPUT_DATE_FORMAT`.** Default parser handles both, and forcing strict ISO input would break user-imported third-party journals.
- **Migration script is a one-shot, not a continuously-running migration.** The writer-side invariant (always emit ISO) prevents regression; ad-hoc external journals that arrive via import would inherit whatever format their source used, but our import path normalizes them.
- **Backup files stay slash-formatted.** They're historical records; mutating them defeats the point.
- **Regression test scans test fixtures, not the user's workspace.** Live workspace varies; test fixtures are committed and stable.
