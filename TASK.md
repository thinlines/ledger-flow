# Current Task

## Title

Preserve matched manual entries via UUID-linked archive journal

## Objective

When a manual transaction is matched to an imported transaction during unknowns review, the manual entry is no longer deleted. It is moved to a non-canonical archive journal and linked to the imported transaction by a shared `match-id` UUID. This closes the acute data-loss bug where matched manual entries disappear permanently on import undo, and establishes the reversible link that a future unmatch action will use.

## Scope

### Included

- New archive file: `workspace/journals/archived-manual.journal`, never `include`d in loaded journals.
- Archive writer: append matched manual entry blocks, stamp each with `; match-id: <uuid>`.
- `unknowns_service.apply_unknown_mappings` match branch: replace in-place deletion with archive-then-remove.
- Stamp `; match-id: <uuid>` on the matched imported transaction, in addition to the existing `; :manual:` tag.
- UUIDv4 generation per match group (one UUID per match, shared between archive entry and main-journal stamp).
- Rollback safety: record archive file size before any write; truncate back on failure before raising.
- Unit tests: archive creation with header, append on subsequent match, match-id consistency, main-journal integrity after archive-move, rollback on simulated write failure.
- Ledger CLI round-trip test: main-journal balances unchanged before vs. after a match.

### Explicitly Excluded

- Unmatch UI, endpoint, or event (delivered by Feature 5d, Transaction Actions Menu).
- Promotion of archived entries back to main journal (delivered by Feature 5d).
- UI browsing or display of archived entries.
- Changes to `include` directives or loaded-journal composition.
- Historical migration of previously-matched entries (prospective only).
- Event-log integration (`match.created.v1` event emission is deferred to Feature 5b).
- Changes to matching logic, match quality ranking, or the `:manual:` tag semantics.
- Git auto-commits of the archive file (deferred to Feature 5c snapshots).

## System Behavior

### Inputs

- User selects `match` in unknowns review and applies the stage.
- `unknowns_service.apply_unknown_mappings(config, stage, selections)` invoked with one or more match selections in `selections`.

### Logic

**1. Generate one match-id per match group**

For each `group` in `scanned_groups` where `selection.selectionType == "match"`:
- Generate `match_id = str(uuid.uuid4())` once per group, stored in a `{group_key: match_id}` map.
- Use the same `match_id` for both the archived manual entry and the imported-transaction stamp.

**2. Stamp match-id on matched imported transactions**

Extend the existing `match_tag_start_lines` loop in [unknowns_service.py:774](app/backend/services/unknowns_service.py#L774). Currently it inserts `    ; :manual:` after the transaction header. After that insert, also insert `    ; match-id: <uuid>` on the following line.

Resulting block order:

```
2026-03-15 * Whole Foods Market
    ; :manual:
    ; match-id: 8f3a2b1c-4d5e-6f78-9012-345678901234
    ; source_identity: abc123...
    Expenses:Groceries              $50.00
    Assets:Checking                -$50.00
```

Preserve the existing dedup guard for `:manual:`; add an equivalent guard for `match-id:` (defensive only — collisions should not occur).

**3. Archive manual entry block before removal**

For each match group, before the existing removal at [unknowns_service.py:820](app/backend/services/unknowns_service.py#L820):
- Extract the manual entry block lines (`lines[found_start:found_end]`, excluding trailing blank lines).
- Insert `    ; match-id: <uuid>` as the second line of the block (immediately after the transaction header).
- Append the modified block to `workspace/journals/archived-manual.journal` via the archive writer helper.
- Then remove the block from the main journal (existing behavior).

**4. Archive file format**

First write creates the file with a three-line header:

```
; Ledger Flow archived manual entries.
; Do NOT include this file in main.journal — it duplicates transactions by design.
; Each entry has a matching `match-id:` tag in a main-journal transaction.

2026-03-15 Whole Foods Market
    ; match-id: 8f3a2b1c-...
    ; :manual:
    Expenses:Groceries              $50.00
    Assets:Checking                -$50.00

```

Subsequent writes append only, separated by one blank line. Header is never rewritten.

**5. Rollback on failure**

At entry to the match-apply section, capture `archive_size_before = archived_path.stat().st_size if archived_path.exists() else None`.

On any exception after archive write but before main-journal write completes: truncate `archived-manual.journal` back to `archive_size_before` (or delete if it was `None`), then re-raise.

### Outputs

- `workspace/journals/archived-manual.journal` exists after any match apply, containing the pre-match manual entry(ies).
- Matched imported transactions in the main journal carry both `; :manual:` and `; match-id: <uuid>` tags.
- The `match-id` values are identical between the archive entry and the main-journal stamp (1:1 link).
- Response payload from `unknowns/apply` is unchanged in shape.

## System Invariants

- `archived-manual.journal` is never `include`d by any loaded journal. Ledger CLI must not see it as part of the user's books.
- Every matched imported transaction has exactly one `match-id:` tag.
- Every entry in `archived-manual.journal` has exactly one `match-id:` tag.
- Each `match-id` in the archive corresponds to exactly one `match-id` in a main-journal transaction (1:1 link, no reuse).
- The archive file is append-only within this task (no updates, no deletes, no rewrites).
- Archive write failure MUST fail the entire apply operation — data integrity for manual entries outranks partial progress. (Contrast: git/snapshot layer is advisory and fails open. Archive is data-path and fails closed.)
- The `.bak` backup of the main journal remains the rollback path for main-journal writes; the archive rollback path is size-truncation.

## States

- **No archive file yet**: first match creates the file with header + first entry.
- **Archive file exists**: subsequent matches append entries with one-line separator.
- **Match with missing manual entry**: existing warning path ("Manual entry is no longer available") — no archive write, no match-id stamp, no main-journal change.
- **Multiple matches in one apply**: each group gets a distinct `match-id`; entries appended in deterministic (group) order.
- **Archive write fails**: archive truncated/removed, main journal unchanged, HTTP 500 raised with context.

## Edge Cases

- **Repeated structurally-identical manual entries**: each gets a distinct UUID. Archive may contain look-alike entries; this is correct — they are distinct matches.
- **Manual entry already carries a `match-id:` tag**: should not occur (would imply prior match). Log warning, skip archive write for that group, continue with removal. Surface a warning in the apply response. This is strictly better than data loss.
- **Concurrent apply requests**: the archive file append uses `open(path, "a", encoding="utf-8")` followed by `write()`. Each apply writes as a single block. Same concurrency caveat as existing journal writes (acknowledged in current codebase).
- **Archive file becomes large**: no cap in v1. 10,000 matches ≈ 2MB. Acceptable. Rotation is deferred.
- **User manually edits `archived-manual.journal`**: file is plain text in the workspace — we don't prevent this. If the `match-id` link is broken, future unmatch fails gracefully (warning, no action).
- **Workspace has no `journals/` directory**: existing code already ensures `journal_path.parent`. Reuse that behavior for the archive path.
- **Archive write succeeds, main journal write fails (disk full mid-write)**: existing `backup_file()` restores main journal via `.bak`. The archive entry is an orphan. Rollback path (step 5 above) truncates the archive to its pre-apply size, so orphan never surfaces.

## Failure Behavior

- **Archive file write fails** (I/O error, permissions, disk full): log error with context, raise `HTTPException(500)`. Do not proceed with manual-entry removal from main journal. User sees an error; both files remain in pre-apply state.
- **Exception between archive write and main-journal write**: truncate archive back to `archive_size_before`, then re-raise. Ensures no orphaned archive entries.
- **Exception during `match-id` stamp insertion** (should be impossible given current validated ranges): main-journal backup via `.bak` is still intact; restore and raise. Archive rolls back per step 5.
- **`uuid.uuid4()` failure**: treat as code error, let it propagate.
- Never raise an HTTP error from archive-path logic without first rolling back archive state.

## Regression Risks

- **Archive file inadvertently `include`d**: if the archive is ever loaded by the ledger CLI, balances double-count matched transactions. **Mitigation**: the archive lives at `workspace/journals/archived-manual.journal` — a path that is NOT referenced in any `include` directive. Add a test that loads the main journal via `ledger_runner` after a match and asserts the balance is unchanged from pre-match.
- **Tag insertion order**: `:manual:` on line 2, `match-id:` on line 3. Changing order risks breaking existing `:manual:` detection in `has_manual_tag()`. **Mitigation**: insert `match-id:` AFTER `:manual:`, and test that `has_manual_tag()` still returns true on post-stamp blocks.
- **Existing fixtures without `match-id:` tags**: tests that assert exact matched-journal content must be updated to include the new line. **Mitigation**: grep tests for match-apply assertions and update each.
- **Staged payloads in `.workflow/stages/*.json`**: already encode manual line ranges; no schema change required. The archive is invisible to staging.
- **`backup_file()` coverage**: main-journal `.bak` is written by existing code before mutation. Archive has no `.bak` — rollback is by size-truncation. Ensure `archive_size_before` is captured BEFORE first archive write.
- **Empty manual entry block extraction**: existing code trims trailing blank lines when computing `found_end`. Reuse that same range when archiving, so the archive entry is clean.

## Acceptance Criteria

- After applying a match in unknowns review, `workspace/journals/archived-manual.journal` exists and contains the previously-manual transaction block.
- The archive entry has a `; match-id: <uuid>` tag as the second line of the block.
- The matched imported transaction in the main journal has both `; :manual:` and `; match-id: <uuid>` tags.
- The `match-id` values on the two records are byte-for-byte identical.
- Running `ledger -f workspace/journals/2026.journal bal` produces balances identical to a control run without this change (archive is not loaded).
- Running `ledger -f workspace/journals/archived-manual.journal bal` loads successfully (valid ledger format).
- A second match on a later apply produces a second archive entry with its own `match-id`; the file is appended to, not rewritten.
- When archive write is simulated to fail, main journal is unchanged and the API returns 500.
- When archive write succeeds but main-journal write is simulated to fail, archive is truncated back to pre-apply size.
- `uv run pytest -q` passes in `app/backend`.
- `pnpm check` passes in `app/frontend` (no frontend change, but verify API contract intact).

## Proposed Sequence

1. **Add archive writer helper** in `unknowns_service.py` (or a new `archive_service.py` if cleaner — judgment call at implementation time). Signature: `archive_manual_entry(workspace_path: Path, match_id: str, block_lines: list[str]) -> None`. Responsibilities: ensure parent dir exists, write header on first call, insert `match-id:` at line 2 of block, append with separator. Unit tests: first write creates file with header; second write appends; path already contains archive with header doesn't duplicate header.
2. **Modify `apply_unknown_mappings` match branch**: generate `match_id_by_group: dict[str, str]` at the top of the match loop; pass the id into the match-tag insertion loop and the manual-removal loop.
3. **Update tag-insertion loop** to insert `match-id:` after `:manual:`. Preserve dedup guard for `:manual:`; add one for `match-id:`.
4. **Update manual-removal loop** to call `archive_manual_entry()` with the extracted block BEFORE deletion. Capture `archive_size_before` at the top of the match-apply section.
5. **Wrap match-apply section in rollback**: on exception, truncate archive to `archive_size_before`, re-raise.
6. **Update affected tests** in `app/backend/tests/` — search for match-apply assertions and journal content comparisons that need the new `match-id:` line.
7. **Add new tests**: archive creation + header, repeated-match append, match-id consistency between archive and main, ledger CLI round-trip (balances unchanged), rollback on simulated archive failure, rollback on simulated main-journal failure after archive write.
8. **Manual verification**: run a real match through the UI; inspect `workspace/journals/archived-manual.journal`; grep the main journal for `match-id`; confirm the UUIDs match up pair by pair.

## Definition of Done

- Every match from unknowns review produces a paired record: main-journal imported transaction with `match-id:` stamp, archive-journal manual entry with the same `match-id:` stamp.
- No scenario deletes user-entered manual transaction content.
- Ledger CLI behavior on the main journal is unchanged (verified by balance comparison before/after).
- The archive file is valid ledger format (verified by `ledger -f` loading).
- Rollback verified: archive writes don't leave orphans when the apply fails.
- All existing tests pass: `uv run pytest -q` and `pnpm check`.
- No UI-visible change (archive is invisible to users until Feature 5d).
- The `:manual:` + `match-id:` contract is documented in code comments at the stamp-insertion site, so a future reader understands the invariant.

## Out of Scope

- Unmatch action (endpoint, UI, or event emission).
- Archive browsing or preview UI.
- Automatic cleanup of orphaned archive entries.
- Historical migration of matches made before this change ships.
- Archive rotation, size caps, or multi-year splitting.
- Event-log emission (deferred to Feature 5b).
- Git auto-commits of the archive file (deferred to Feature 5c).
