# Task 07 — Delete `Scripts/BankCSV.py`, Schwab, and Bank of Beijing

## Title

Land three tightly-scoped commits: first delete Schwab support in isolation, then delete BJB support in isolation, then delete `Scripts/BankCSV.py` and remove the legacy fallback in `csv_normalizer.py`.

## Objective

Retire the legacy parser monolith. Leave the repo in a state where `services/parsers/` is the only CSV-parsing path for institution accounts (custom CSVs stay on their own path via `custom_csv_service.py`).

## Context

This is the terminal task of the refactor. After it lands:

- `Scripts/BankCSV.py` no longer exists.
- `charles_schwab` and `bank_of_beijing` are no longer supported institutions.
- `csv_normalizer.py` no longer has a `_load_create_bank_csv` helper or a fallback branch.
- Every CSV import for a supported institution (Wells Fargo, Alipay, ICBC) routes through an adapter.

**Per locked user instruction (memory `project_csv_parser_refactor.md`):** Schwab deletion **must be its own git commit**, separate from `BankCSV.py` deletion. BJB follows the same pattern so both become easy to locate and revert if ever needed later. Rationale: if brokerage or BJB support is revisited, the "remove <institution>" commit is easy to find in git log and revert-source for its BankCSV subclass.

## Scope

### Included

**Commit A — Remove Schwab (in isolation):**

- In `app/backend/services/institution_registry.py`: delete the Schwab entry from `_LEGACY_BRIDGES` (the tuple set up in Task 06). After this commit, `list_templates()` returns 4 entries (WF, Alipay, ICBC, BJB) instead of 5.
- In `Scripts/BankCSV.py`: delete the `SchwabCSV` class (lines ~214-285) and remove `"schwab"` and `"charles_schwab"` entries from the `institutions` dict in `create_bank_csv` (lines 23-24). The rest of the file stays intact.
- Do **not** delete `Scripts/BankCSV.py` in this commit.
- Remove any Schwab references in tests: grep for `schwab`, `Schwab`, `charles_schwab`, `SchwabCSV`. Delete fixtures, test stubs, or parametrizations.
- Remove Schwab from workspace bootstrap defaults if present.
- Commit message format: `refactor: remove Schwab CSV support (brokerage out of scope)`.

**Commit B — Remove Bank of Beijing (in isolation):**

- In `app/backend/services/institution_registry.py`: delete the BJB entry from `_LEGACY_BRIDGES`. After this commit, `list_templates()` returns 3 entries (WF, Alipay, ICBC).
- In `Scripts/BankCSV.py`: delete the `BjbCSV` class (lines ~129-164) and remove `"bjb"` and `"bank_of_beijing"` entries from the `institutions` dict.
- Remove any BJB references in tests: grep for `bjb`, `BjbCSV`, `bank_of_beijing`, `beijing`. Delete fixtures, test stubs, or parametrizations.
- Remove BJB from workspace bootstrap defaults if present.
- Commit message format: `refactor: remove Bank of Beijing CSV support (YAGNI, 2026-04-15 scope trim)`.

**Commit C — Delete `Scripts/BankCSV.py` + legacy fallback:**

- Delete `Scripts/BankCSV.py` entirely. At this point, the file contains only the `BankCSV` base class, `AlipayCSV`, `IcbcCSV`, `WellsFargoCSV`, the WF aliases, and the `create_bank_csv` dispatch function — all dead code since every remaining institution has an adapter.
- If the `Scripts/` directory is now empty, delete the directory.
- In `app/backend/services/csv_normalizer.py`:
  - Remove the `@lru_cache(maxsize=1)` `_load_create_bank_csv()` helper and its `importlib.util` import.
  - Remove the fallback branch. The function should terminate after the adapter dispatch with: if no adapter registered for the institution, raise `ValueError(f"No adapter registered for institution {institution_template_id!r}")`.
- In `app/backend/services/institution_registry.py`: remove the `_LEGACY_BRIDGES` tuple — it's now empty. Simplify `_build_registry()` to iterate adapters only.
- `grep -rE "BankCSV|create_bank_csv|_load_create_bank_csv|SchwabCSV|BjbCSV|_LEGACY_BRIDGES" app/backend/` must return no hits.
- Commit message format: `refactor: delete Scripts/BankCSV.py; adapter registry is the only institution path`.

**Verification (no code changes):**

- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q` green for the three supported institutions (WF, Alipay, ICBC).
- `uv run pytest app/backend/tests/ -q --ignore=app/backend/tests/test_unknown_stage_resume.py --ignore=app/backend/tests/test_workspace_bootstrap.py` green.
- Manual end-to-end import test against at least one real CSV (Wells Fargo) — verify the preview still produces the expected intermediate and the idempotency check still identifies previously-imported transactions as duplicates. **If any previously-imported transaction re-surfaces as "new", the hash stability invariant is broken — revert immediately.**

### Explicitly excluded

- No adapter behavior changes.
- No frontend changes.
- No removal of the "No adapter registered" error message — we want it loud if someone adds a new institution later without an adapter.
- No reorganization of the `services/parsers/implementations/` package layout.
- No cleanup of the `Record.currency` / writer format rules (post-refactor follow-up).
- No normalization of the amount vs. total thousand-separator inconsistency.

## System Behavior

**Inputs (after all three commits):** same as before — `normalize_csv_to_intermediate(config, csv_path, account_cfg)`.

**Logic:** resolve institution → if custom, delegate to custom service; else slice head/tail → look up adapter → raise if not found → parse → translate → reverse → write. No fallback.

**Outputs:** identical for Wells Fargo, Alipay, ICBC (byte-exact, verified by Task 0 fixtures). Schwab and BJB are no longer supported — any attempt raises.

## System Invariants

- Wells Fargo, Alipay, ICBC intermediate output stays byte-exact.
- Import identity hashes for previously-imported transactions stay identical — no re-import surprise on a user's workspace.
- `Scripts/BankCSV.py` does not exist.
- Neither `charles_schwab` nor `bank_of_beijing` is in `_ALIAS_TO_ID` or `_REGISTRY`.
- `services/parsers/implementations/` is the only place CSV parsing logic lives for institutions.

## States

Not applicable.

## Edge Cases

- **User has a workspace with an active Schwab or BJB import account.** After the corresponding commit, that account fails to preview with `KeyError` or `ValueError`. This is the accepted outcome — both institutions are out of scope per locked design. **Mitigation:** document the user-facing error in delivery notes; user removes the affected import account from `workspace/settings/workspace.toml` before upgrading.
- **Workspace config has a custom institution aliased to `"schwab"` or `"bjb"`.** After the corresponding commit, the alias no longer maps. Custom institutions go through `custom_csv_service`, not this path, so no impact.
- **Test fixtures reference Schwab or BJB.** Grep before each commit; delete any such fixtures and update parametrizations.
- **Third-party tooling imports `Scripts.BankCSV`.** Grep the whole repo; if anything external depends on `BankCSV`, it's broken. None found in Task 0's Explore report; confirm again pre-commit.
- **Git history preservation.** `git log --diff-filter=D -- Scripts/BankCSV.py` finds Commit C. `git log -p -S "class SchwabCSV" -- Scripts/BankCSV.py` finds Commit A (the class deletion). Same for BJB via Commit B.

## Failure Behavior

- **A previously-imported transaction surfaces as "new" after Commit C.** Byte-exact invariant broken. Revert Commit C (or more if needed), investigate.
- **`test_csv_parser_fixtures.py` fails at any commit.** The commit made a covered path silently wrong. Revert, identify, fix.
- **Workspace bootstrap fails because Schwab or BJB was present in the default config.** Remove the offending institution from bootstrap defaults (check `workspace_service.py`) as part of the corresponding commit.

## Regression Risks

- **Residual BankCSV / SchwabCSV / BjbCSV import.** A module outside `services/` may dynamically import these in a way grep misses. Mitigation: run the full backend test suite; any ImportError at collection surfaces it.
- **Adapter silently missing for an institution that was never routed through the dispatch seam.** After Task 06, every supported institution has either an adapter (WF/Alipay/ICBC) or a legacy bridge (Schwab/BJB). Commits A and B remove the legacy bridges. Commit C removes the fallback. Any non-adapter-backed institution after all three commits errors loudly — acceptable.
- **`custom_csv_service` path accidentally affected.** Commit C changes to `csv_normalizer.py` happen after the `if source["mode"] == "custom":` branch. Custom path unaffected. Verify with grep + an end-to-end custom-CSV preview.
- **Hash identity drift.** Impossible in principle — Wave 2 / Wave 3 shipped byte-exact golden tests — but if a silent change slipped through, Commit C could expose it. Run full backend test + manual preview on a real user CSV before calling the task done.
- **Bisect unfriendliness.** Bundling the three commits breaks user instruction. Keep them separate. The bisect-friendliness payoff is that "`git log -- Scripts/BankCSV.py`" shows obvious per-institution removal commits.

## Acceptance Criteria

- `ls Scripts/BankCSV.py` → "No such file or directory".
- `grep -rE "BankCSV|create_bank_csv|SchwabCSV|BjbCSV|charles_schwab|bank_of_beijing" app/backend/ Scripts/ 2>/dev/null` returns no matches (the institution slugs may still appear in test fixtures related to deprecation messages; grep the service code specifically).
- `uv run pytest app/backend/tests/test_csv_parser_fixtures.py -q` green for the three supported institutions.
- `uv run pytest app/backend/tests/ -q --ignore=app/backend/tests/test_unknown_stage_resume.py --ignore=app/backend/tests/test_workspace_bootstrap.py` green.
- `uv run python -c "from app.backend.services.institution_registry import list_templates; print(sorted(t.id for t in list_templates()))"` prints `['alipay', 'icbc', 'wells_fargo']`.
- `git log --oneline --diff-filter=D -- Scripts/BankCSV.py` returns exactly one commit (Commit C).
- `git log -p --all -- Scripts/BankCSV.py | grep -c "class SchwabCSV"` ≥ `1` (Schwab source remains in history).
- `git log -p --all -- Scripts/BankCSV.py | grep -c "class BjbCSV"` ≥ `1` (BJB source remains in history).

## Proposed Sequence

1. **Pre-flight grep.** `grep -rE "Schwab|schwab|charles_schwab|SchwabCSV|BjbCSV|bank_of_beijing|beijing" app/backend/ Scripts/` — enumerate every reference. Collect into a list.
2. **Commit A: Schwab removal.**
   - Delete `SchwabCSV` class + `institutions` dict entries from `Scripts/BankCSV.py`.
   - Delete Schwab from `_LEGACY_BRIDGES` in `institution_registry.py`.
   - Delete Schwab-related test fixtures or parametrizations.
   - Remove from workspace bootstrap defaults if present.
   - Run full test suite — green.
   - Commit.
3. **Commit B: BJB removal.**
   - Delete `BjbCSV` class + `institutions` dict entries from `Scripts/BankCSV.py`.
   - Delete BJB from `_LEGACY_BRIDGES`.
   - Delete BJB-related test fixtures or parametrizations.
   - Remove from workspace bootstrap defaults if present.
   - Run full test suite — green.
   - Commit.
4. **Commit C: BankCSV.py deletion + fallback removal.**
   - Delete `Scripts/BankCSV.py`.
   - Remove `_load_create_bank_csv` and fallback branch from `csv_normalizer.py`. Add clear `ValueError` for unregistered institutions.
   - Remove `importlib.util` import if only used for the fallback.
   - Remove the now-empty `_LEGACY_BRIDGES` tuple from `institution_registry.py`; simplify `_build_registry()`.
   - Run full test suite — green.
   - Manually preview a real WF CSV — verify byte-exact intermediate + duplicate detection.
   - Commit.
5. **Post-commit cleanup (this task's final commit or a follow-up):**
   - Delete `tasks/` directory (all briefs + MANIFEST).
   - Delete `Scripts/` directory if empty.
   - Update `ROADMAP.md` Standing Work section to remove the refactor track.
   - Update memory `project_csv_parser_refactor.md` — either add a completion line or delete if no longer load-bearing.

## Definition of Done

- All three commits landed on master in order (A → B → C).
- All tests green.
- Real-world import tested end-to-end for at least one institution.
- No residual `BankCSV.py` / `SchwabCSV` / `BjbCSV` references in the repo.
- Schwab and BJB each searchable in git history as a single deletion commit.
- `tasks/` and `Scripts/` cleaned up per step 5.

## Dependencies

- **Task 06** — Schwab and BJB must exist as hardcoded bridges in `_LEGACY_BRIDGES` before Commits A and B remove them (otherwise the deletions are spread across multiple files and the bisect story gets muddier).
- **Tasks 01, 02, 04, 05** — all adapter-backed banks route through adapters.

## Out of Scope

- Normalization of currency-formatting quirks.
- Post-refactor reorganization of `services/parsers/implementations/`.
- Adding new institutions.
- Re-introducing Schwab, BJB, or securities support.
