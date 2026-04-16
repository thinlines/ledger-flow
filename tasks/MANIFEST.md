# CSV Parser Refactor — Task Manifest

Multi-wave execution plan for the remaining tasks of the `Scripts/BankCSV.py` → `app/backend/services/parsers/` refactor. Task 0 (scaffolding + WF/Alipay/ICBC golden fixtures) shipped 2026-04-14.

Full design rationale lives in memory (`project_csv_parser_refactor.md`). The load-bearing constraint is **import-identity hash stability**: every task must keep the intermediate CSV byte-exact so `source_identity` / `source_payload_hash` do not drift and cause already-imported transactions to reappear as "new" on reimport.

## Scope Trim (2026-04-15)

The originally sketched 7-task sequence included two YAGNI items cut by the user after planning:

- **`generic.credit` translator** — pure scaffolding; no bank in the sequence ported to it. Cut.
- **Bank of Beijing adapter + fixture** — user does not import BJB and the support does not justify the maintenance surface. Cut. BJB joins Schwab as "deleted during refactor" — removed from `institution_registry` and from `Scripts/BankCSV.py` as part of Task 07 in its own isolated commit for git-history locality.

After the trim, the refactor ships six execution tasks (01, 02, 04, 05, 06, 07). Task-number gaps (03, 06a absent) are preserved so references from older planning artifacts still resolve.

## Wave Structure

| Wave | Tasks | Mode | Rationale |
|------|-------|------|-----------|
| 1 | [01 — active at `TASK.md`](../TASK.md) | sequential | Writer contract blocks all translator work |
| 2 | [02](02-wf-adapter-and-dispatch.md) | sequential | Establishes dispatch seam in `csv_normalizer.py` + reference adapter/translator |
| 3 | [04](04-alipay-adapter.md), [05](05-icbc-adapter.md) | **concurrent** | No file overlap; both register against the Wave-2 seam |
| 4 | [06](06-institution-registry-derivation.md) | sequential | Needs both Wave-3 adapters registered |
| 5 | [07](07-delete-bankcsv-schwab.md) | sequential | Deletes legacy code; Schwab and BJB each removed in their own isolated commits |

## Task List

- [01 — Intermediate CSV writer](../TASK.md) — **active** (promoted to `TASK.md`). `services/parsers/intermediate_writer.py`; extend `types.py` with `Record.balance` / `Record.note` / `LedgerTransaction.balance`.
- [02 — WF adapter + dispatch seam](02-wf-adapter-and-dispatch.md) — `csv_normalizer.py` routes to registered adapters; implements `wells_fargo` adapter + `generic.checking` translator.
- [04 — Alipay adapter](04-alipay-adapter.md) — GB18030 pre-decoded text, income/expense merge.
- [05 — ICBC adapter](05-icbc-adapter.md) — debit/credit split columns, `美元→USD` / default CNY currency mapping.
- [06 — Institution registry derived from adapter registry](06-institution-registry-derivation.md) — `institution_registry._REGISTRY` becomes generated state; Schwab + BJB stay hardcoded until 07.
- [07 — Delete `Scripts/BankCSV.py` + Schwab + BJB](07-delete-bankcsv-schwab.md) — three isolated commits (remove Schwab, remove BJB, delete BankCSV + fallback).

## Independence Assessment — Wave 3

Every Wave-3 task adds new files only. Zero pre-existing files modified by either task.

| Task | New files | Pre-existing files modified |
|------|-----------|------------------------------|
| 04 | `services/parsers/implementations/alipay.py`, `tests/test_alipay_adapter.py` | none |
| 05 | `services/parsers/implementations/icbc.py`, `tests/test_icbc_adapter.py` | none |

**Verdict: no file overlap between the two Wave-3 tasks.** Safe to run in two worktrees concurrently and merge in any order. No edit to `tests/test_csv_parser_fixtures.py` is needed by either task — the existing Task 0 parameterization already covers both institutions, and once an adapter registers, the dispatch seam from Task 02 routes the parameterized test through the new pipeline automatically.

## Cross-Wave Merge Order

- **01 → 02**: Task 02 imports the intermediate writer. Merge 01 first.
- **02 → 04, 05**: Wave-3 tasks register against the Wave-2 dispatch seam. Without 02, registering an adapter has no runtime effect (legacy BankCSV path still wins).
- **04, 05 → 06**: Registry-derivation reads the set of registered adapters. Both Wave-3 adapters must exist at merge time, otherwise the derived `_REGISTRY` silently loses entries.
- **06 → 07**: 07 deletes `Scripts/BankCSV.py` and the Schwab + BJB bridges. The dispatch seam must fall through to adapters for every adapter-backed institution (verified in 06), and Schwab + BJB must be removable without breaking other institutions (verified in 07).

## Contract Stability

The dispatch seam contract (set in Task 02, consumed by Tasks 04 and 05) is intentionally narrow:

- `adapter.name` = institution slug (matches `account_cfg["institution"]` after canonicalization).
- `adapter.parse(text: str) -> Iterator[Record]` — text is already decoded and head/tail-sliced; adapter does not touch files.
- `translator.translate(record: Record, account: str) -> LedgerTransaction` — `account` is the ledger account path (e.g., `Assets:Bank:Wells Fargo:Checking`).
- `intermediate_writer.write_intermediate(transactions: Iterable[LedgerTransaction]) -> str` — caller handles ordering (newest-first reversal).

If a Wave-3 task surfaces a needed contract change (most likely: per-institution amount/total formatting quirks that can't be captured in the writer alone), the fix path is:

1. Stop the affected Wave-3 task.
2. Amend Task 02's brief with the revised contract.
3. Land the amendment; rebase the other Wave-3 branch against it.
4. Resume.

Do not hack around a contract gap inside a Wave-3 task — that defeats the point of the seam and pollutes the architecture.

## Shared Constraints (apply to all tasks)

- **Byte-exact regression oracle.** `app/backend/tests/test_csv_parser_fixtures.py` continues to compare `normalize_csv_to_intermediate()` output against Task 0 golden fixtures. Once an adapter registers, the test routes through the new pipeline end-to-end for that institution and must pass without fixture edits.
- **`Scripts/BankCSV.py` stays frozen until Task 07.** If a bug is found in BankCSV during the refactor, regenerate the affected fixture in the same commit as the fix; do not silently invalidate the oracle.
- **No user-visible changes.** No API payloads, no frontend, no config, no UI copy.
- **Custom CSV pipeline is untouched.** `services/custom_csv_service.py` stays on its own path through Task 07. This refactor is institution-only.
- **Schwab and BJB policy.** Both remain wired through BankCSV.py through Task 06. Task 07 deletes Schwab's class and registry entry in its own commit, BJB's class and registry entry in its own commit, then `Scripts/BankCSV.py` itself in a third commit. Per user instruction: easy to locate in history if brokerage or BJB support ever returns.
- **No backwards-compatibility shims.** After Task 07 lands, the old BankCSV path is gone. If Task 07 exposes a consumer we missed, fix the consumer or revert.

## Execution Tips

- **Worktrees for Wave 3.** Use two worktrees for Tasks 04 and 05. Each agent/developer owns its own worktree, implements, commits, and merges back to master. Per project convention in memory (`feedback_worktree_agents.md`), worktree agents must commit before returning, and the main branch merges rather than patches.
- **Task 0 existing test is the shared oracle.** For Wave 3, the regression check for Tasks 04/05 is not a new test file — it's the existing `test_csv_parser_fixtures.py` replaying through the adapter. An adapter-level unit test file is still recommended per task to isolate failures.
- **Running `pytest` remains pre-existing-environment-sensitive.** The fastapi ModuleNotFoundError captured in Task 0's Delivery Notes still affects broader test runs. Use `uv run pytest app/backend/tests/test_csv_parser_fixtures.py app/backend/tests/test_<bank>_adapter.py -q` for targeted work.

## Post-Completion Cleanup

When Task 07 lands:

1. Delete the `tasks/` directory (briefs + this manifest).
2. Delete `Scripts/` if empty (it will be after 07).
3. Update `ROADMAP.md` → remove the "CSV parser refactor" track from Standing Work.
4. Update memory `project_csv_parser_refactor.md` with a completion line or delete the memory if no longer load-bearing.
5. `git log --oneline` spot-check: Schwab-deletion commit, BJB-deletion commit, and BankCSV-deletion commit should each stand alone and be searchable by `git log -- Scripts/BankCSV.py` and by grep on the institution slug.
