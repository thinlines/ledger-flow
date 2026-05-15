# Import redesign — preview step, confirm action, one-column layout

## Objective

The `/import` page becomes a one-column surface where the user selects a source (drop zone or inbox), sees an inline preview summary (counts), and confirms with one click. The auto-apply pattern is removed: imports no longer fire silently behind the user's back. Post-apply, the toast directs the user to Review. Layout moves to a drop zone, inbox-first column, and compact history.

This task supersedes `tasks/import-layout.md` (layout-only, now merged here) and amends the behavioral foundation from `tasks/import-flow.md` (completed 2026-05-12).

## Dependencies

Merges after `tasks/import-flow.md` (completed). Replaces `tasks/import-layout.md` entirely.

## §21 Amendment

Current §21 says: *"Imports apply silently with an undoable toast for the routine path."*

Revised intent: **Imports auto-preview when selection is complete. The preview summary is shown inline. The user confirms with one click. Apply fires, toast confirms with undo + link to Review. Only `reconciled_date_fence` conflicts interrupt with the conflict view.**

The backend contract is unchanged. The change is frontend orchestration: the `triggerImport()` chain now stops after preview and waits for user confirmation instead of auto-applying.

## Scope

### Included

- **Behavioral fix**: Separate auto-preview from auto-apply. Show inline preview summary. Add explicit "Add N transactions" button.
- **Drop zone**: Replace `<input type="file">` with a dashed-border drop zone (drag-and-drop + click-to-browse).
- **One-column layout**: Remove the right-rail `<aside>`. Inbox in main column. Drop zone below inbox (or primary when inbox empty).
- **Inbox management**: Subtle trash icon on each inbox row for removal without importing.
- **Post-import direction**: Toast includes "Review →" link to `/review`.
- **Copy diet**: Remove page hero, eyebrows, subtitles, workflow footer.
- **Year override removal**: Remove the year selector entirely. The backend defaults to current year; year-switching and journal-closing don't exist yet, so the control is premature.
- **Compact history**: Single-line rows, 5-entry default with "Show all" expander.
- **Preview auto-refresh**: Re-preview when account changes while a source is selected.

### Explicitly excluded

- Backend changes — `/api/import/upload`, `/api/import/preview`, `/api/import/apply` contracts unchanged. **Exception:** `/api/import/candidates` response gains optional `transaction_count` and `date_range` fields on each candidate (lightweight CSV header scan at scan time).
- Year override UI — removed entirely (no year-switching or journal-closing exists yet). Backend continues to default to current year.
- Recovery card layout changes.
- Multi-file drop.
- Review page changes (Match button availability is a separate fix).
- Mobile bottom sheet or other new mobile chrome.

## System Behavior

### Inputs

- User drags a CSV onto the drop zone.
- User clicks the drop zone to open the OS file picker.
- User clicks an inbox row (selects it, does NOT auto-import).
- User selects an import account from the dropdown.
- User clicks "Add N transactions" to confirm.
- User clicks the trash icon on an inbox row to remove it.
- User clicks "Show all / Show fewer" on history.
- User clicks the info icon on a history row.

### Logic

#### Selection + auto-preview (replaces auto-trigger)

When both a source (file or inbox candidate) and an import account are set:
1. If source is a dropped file: auto-upload to inbox via `POST /api/import/upload?preview=true`. On success, the file appears as an inbox candidate; the file input clears (this is expected — the file is now in the inbox). The upload response includes preview data.
2. If source is an inbox candidate: auto-preview via `POST /api/import/preview`.
3. Show the preview result inline: `"N new · M already imported"`.
4. **Stop here.** Do not auto-apply. Wait for user to click "Add N transactions."

If either source or account is missing, show a contextual hint:
- Source selected, no account: `"Choose an account to continue."`
- Account selected, no source: the drop zone / inbox list is the obvious next step (no extra hint needed).

#### Confirm + apply (user-initiated)

When the user clicks "Add N transactions":
1. `loadingState = 'apply'` — button shows "Adding…"
2. `POST /api/import/apply` with the staged `stageId`.
3. On success: show toast with undo + "Review →" link. Clear selection. Reload data.
4. On fence conflict (from preview): transition to the existing conflict-resolution view instead of showing the confirm button.

#### Preview auto-refresh

When account changes while a preview is showing, re-preview automatically. The confirm button updates with new counts.

#### Inbox row removal

Each inbox row has a trailing trash icon. Click → `window.confirm("Remove <filename> from the inbox?")` → `POST /api/import/remove`. No selection required. The trash icon is always visible, not gated on selection state.

#### Drop zone

- Large, visually prominent dashed border, centered icon + `"Drop a CSV here, or click to browse"`.
- Drag handlers: `dragover` adds `drag-active` class; `dragleave` removes it; `drop` reads first file, validates type (`.csv` or `text/csv`), dispatches same handler as click-to-browse.
- Click delegates to a hidden `<input type="file">`.
- Keyboard accessible: `<button>` with Enter/Space activation.
- Always the hero element at the top of the page — never demoted or shrunk. Whether the inbox is empty or full, the drop zone remains visually dominant.

#### Layout

Single column, no right-rail:
1. (Optional) short H1 `"Import"` — no subtitle.
2. **Drop zone — always the visual hero.** Large, prominent dashed-border area with clear drag-and-drop affordance. This is the primary call-to-action regardless of inbox state. When inbox is empty, it's the only surface. When inbox is populated, it remains visually dominant above the inbox list.
3. Account selector — inline within or directly below the drop zone.
4. Inbox list — below the drop zone when `candidates.length > 0`.
5. Preview summary + confirm button — appears inline below the selected row (animated, no layout shift).
6. Compact import history — at the bottom.

#### Compact history

- `let showAllHistory = false`.
- Render `historyEntries.slice(0, showAllHistory ? Infinity : 5)`.
- Each row: `<short date> · <account> · +N added · [Undo] · [info icon]`.
- Info icon expands inline detail row (one open at a time) with paths and recovery info.
- "Show all N" / "Show fewer" trigger when `historyEntries.length > 5`.
- Status: omit glyph for `applied` (default); render `Undone` text for undone entries.

### Outputs

- Empty inbox: dashed-border drop zone as primary surface.
- Populated inbox: scannable list with smaller drop zone below.
- Source + account selected, preview loading: inline "Checking…" indicator.
- Source + account selected, preview ready: `"N new · M already imported"` summary + "Add N transactions" primary button.
- Source + account selected, N = 0: `"Nothing new to add — M already imported"` message, no confirm button.
- Applying: button shows "Adding…", disabled.
- Success: toast `"Added N transactions · Undo · Review →"`. Selection cleared. History refreshed.
- Fence conflict: existing conflict-resolution view takes over (unchanged from Task A).

## System Invariants

- **Selection ≠ execution.** Clicking an inbox row selects it; it does NOT trigger apply. Only the explicit confirm button triggers apply.
- **Upload is immediate; apply is gated.** File upload to inbox happens automatically on drop/browse (reversible via trash icon). Journal writes require user confirmation.
- **Preview is non-destructive.** The preview endpoint classifies transactions but writes nothing.
- Drag-and-drop must not bypass file-type filtering.
- Inbox rows remain keyboard-reachable as `<button>` elements.
- Drop zone is keyboard-reachable via a `<button>` that delegates to the file input.
- History compaction reduces visual weight, not data. Every field surfaced today is still reachable via the inline detail row.
- No `ledger`, `journal`, `posting`, `workspace` terminology in default UI copy. Expanded history detail row may retain path strings.
- **No layout shift on state transitions.** Dynamic regions (preview summary, error messages) must animate into reserved space — surrounding content never jumps.
- **Inbox rows lead with meaning, not filenames.** The primary label is the institution or import account name; the raw filename is secondary.
- Setup mode retains its "first import" framing — essential setup copy attached to the setup-mode template, no eyebrow chrome.

## States

| State | UI |
|-------|-----|
| Inbox empty, no file | Drop zone hero + account selector; no inbox list |
| Inbox populated, nothing selected | Drop zone hero at top; inbox list below |
| Source selected, no account | Selected row highlighted; `"Choose an account to continue."` hint |
| Source + account set, previewing | Selected row highlighted; `"Checking…"` inline indicator |
| Source + account set, preview ready, N > 0 | Summary: `"N new · M already imported"`; primary button: `"Add N transactions"` |
| Source + account set, preview ready, N = 0 | `"Nothing new to add — M already imported"` — no confirm button |
| Applying | Button shows `"Adding…"`, disabled |
| Applied (transient) | Toast with undo + "Review →"; selection clears; history refreshes |
| Fence conflict | Conflict-resolution view (existing, unchanged) |
| Drag-over | Drop zone border + background tint |
| Drop rejected (non-CSV) | Brief feedback below drop zone: `"Choose a CSV file"` |
| History empty | Single line: `"No imports yet."` |
| History collapsed (N > 5) | First 5 entries + `"Show all N"` |
| History expanded | All entries + `"Show fewer"` |
| History row expanded | Inline detail row beneath the open row |

## Edge Cases

- **Single import account**: Auto-selected (existing behavior). Preview fires as soon as a source is also set. User still confirms.
- **File picked before account**: File uploads to inbox on drop. Preview waits for account selection. File input clears (file is now an inbox candidate — visible in the list). No confusing "reset."
- **Inbox candidate marked "Needs setup"**: Row remains visible. Selection shows `"Choose an account to continue."` hint. Trash icon still available.
- **Rapid source changes**: Preview cancellation via the existing `lastTriggerKey` idempotency guard. Only the latest selection previews.
- **Non-CSV drop**: Reject with brief feedback. No console error.
- **Multiple files dropped**: Take the first valid CSV; ignore others with `"Multiple files — using <name>"`.
- **Long file names in inbox**: Existing `wrap-anywhere`. Row height may grow.
- **Long file names in compact history**: Truncate with `text-overflow: ellipsis`; full name in expanded detail row.
- **50+ history entries**: Render all (no virtualization — current high-water mark is 33).

## Failure Behavior

- Upload failure → error message below the drop zone / selected row. Selection preserved so user can retry.
- Preview failure → error message inline. Selection preserved. User can change account and re-preview.
- Apply failure → error message inline. Confirm button re-enables. Selection preserved.
- Non-CSV drop → ignore + brief feedback.
- Empty drop → no-op.
- History fetch failure → existing error-text path; compact list renders empty.

## Regression Risks

- **Auto-apply removal breaks setup wizard.** Setup mode's `onApplied` callback must still fire after the user clicks confirm. Verify the first-import wizard completes end-to-end.
- **Rapid file-change race.** After removing auto-apply, the risk is lower — but verify that preview cancellation on source change still works (stale preview from file A shouldn't show when file B is selected).
- **Inbox row click behavior change.** Previously, clicking a row auto-imported. Now it selects. Verify the visual selected state (`row-selected` class) persists and the preview loads.
- **Drag listener leaks.** Add/remove listeners via Svelte lifecycle. Attach to the drop-zone element, not `document`.
- **Click-vs-drop validation divergence.** Centralize file-type check.
- **Inbox row hit area vs drop zone.** Siblings, not nested. Verify pointer events route correctly.
- **Eyebrow stripping loses affordance.** Without labels, the inbox list + its Ready/Needs setup pills must carry the meaning.
- **Setup-mode copy loss.** Re-attach essential setup framing directly in the setup-mode template.
- **Recovery card placement.** New one-column flow must not push it off-screen.
- **Toast "Review →" link.** Must not render when there are no new unknown transactions (e.g., all imported transactions matched by rules). Only show when `unknownCount > 0` if backend returns it; otherwise always show as a soft suggestion.

## Acceptance Criteria

1. Clicking an inbox row SELECTS it (visual highlight) and does NOT immediately import. The import does not fire until the user clicks "Add N transactions."
2. Selecting a source + account shows an inline preview: `"N new · M already imported"`.
3. Preview with N > 0 shows a primary "Add N transactions" button. Clicking it applies the import.
4. Preview with N = 0 shows `"Nothing new to add"` with no confirm button.
5. Successful apply shows a toast with undo affordance and "Review →" link.
6. Dropping a CSV auto-uploads to inbox and shows the file as a new inbox candidate. The file then follows the same select → preview → confirm flow.
7. Each inbox row has a trash icon that removes the file without importing it.
8. Drop zone is always the visual hero at the top — large, prominent, and never demoted regardless of inbox state.
9. One-column layout with no right-rail `<aside>`. Inbox list appears below the drop zone when populated.
10. Page hero, eyebrows, and subtitles are removed.
11. History renders as compact single-line rows. Default 5 entries with "Show all N" expander.
12. History row info icon expands inline detail; opening one collapses another.
13. Changing the account while a preview is showing re-previews with the new account.
14. Setup mode still completes a first import end-to-end via `onApplied`.
15. Inbox rows display the detected account name as the primary label, with transaction count and date range as secondary info when available. Raw filenames never headline a row.
16. Preview summary animates into view (no instant layout jump). Surrounding elements transition smoothly.
17. `pnpm check` passes with 0 errors and 0 warnings.
18. `pnpm build` succeeds.

## Proposed Sequence

1. **Decouple selection from apply.** Refactor `triggerImport()` to stop after preview. Store the preview result (stage + counts) in component state. Remove the auto-apply path. Add a `confirmApply()` function gated on the stored stage.
2. **Add inline preview summary.** Render the preview counts and "Add N transactions" button below the selected source. Handle the N = 0 case.
3. **Wire the confirm button** to `applyStage()`. On success, show toast with "Review →" link via `showImportUndoToast`. Clear selection. Reload data.
4. **Add trash icon to inbox rows.** Render a small trash/X icon at the trailing edge of each row. Wire to the existing `removeSelectedCandidate` logic (adapted to take any candidate, not just the selected one).
5. **Build the drop zone.** Dashed-border component (inline or extracted): hidden file input, drag handlers, file-type validation, keyboard accessible.
6. **Wire the drop zone.** Replace the `<input type="file">` in both setup and standalone modes. File dispatches through the same `onStatementFileChange` handler → auto-upload → appears as inbox candidate.
7. **Restructure to one column.** Drop the right-rail `<aside>`. Move inbox into the main column. Conditional layout: inbox above drop zone when populated; drop zone alone when empty.
8. **Strip chrome.** Remove page hero, eyebrows, subtitles, workflow footer.
9. **Compact history rows.** Single-line layout: date · account · +N · Undo · info icon. Inline detail row on info-icon click (single-open). "Show all / Show fewer" toggle.
10. **Setup-mode parity.** Analogous one-column layout with drop zone. Essential setup framing re-attached. First-import wizard verified.
11. **Mobile sweep.** Verify under 980px.
12. **`pnpm check`, `pnpm build`.**

## Definition of Done

- All acceptance criteria pass.
- User can: select a source → see preview counts → confirm → see toast with undo + Review link. At no point does the import fire without user confirmation.
- Drop zone accepts `.csv` files on Chromium and Firefox; rejects others without console error.
- Inbox files can be removed via trash icon without triggering an import.
- Setup wizard's first-import flow still completes from a blank workspace.
- No console warnings or unhandled promise rejections during a 5-minute exercise.

## UX Notes

- **Drop zone (hero):** 2px dashed border, generous padding (~160px tall), centered upload icon + `"Drop a CSV here, or click to browse"`. Visually dominant — the first thing the eye hits. Mint-tinted background on dragover (~5% opacity), solid border on dragover. Always full-width and prominent regardless of inbox state. Account selector sits inline within or directly below the drop zone to keep the import action self-contained.
- **Preview region (no layout shift):** The preview summary occupies a reserved slot directly below the selected inbox row. When no preview is active, the slot collapses with a CSS transition (`grid-template-rows: 0fr → 1fr` or `max-height` + opacity fade, ~200ms ease). Content never appears by shoving sibling elements — the transition animates the space open. The preview card visually attaches to the selected row (slight indent or connected-card background tint) to maintain the selection → outcome link.
- **Inbox row presentation:** Primary label is the detected import account name (e.g., "Wells Fargo Checking"). Secondary line shows transaction count and date range if parsing has already occurred (e.g., "34 transactions · Jan 3 – Feb 1"); if not yet parsed, skip the secondary line entirely. Raw filename never shown as a headline — only as a fallback primary label when no account is detected. The "Ready" / "Needs setup" pill remains trailing.
- Compact history: date in short month-day (`May 3`); account short name; `+N` in green; Undo subtle secondary; info icon small muted glyph.
- Trash icon on inbox rows: small, muted, trailing. No label — icon only with `aria-label="Remove from inbox"`.
- Toast "Review →" link: plain text link after the undo button, navigates to `/review`.

## Out of Scope

- Backend changes.
- Multi-file drag-and-drop.
- Inbox row content changes.
- Recovery card layout changes.
- Review page Match button fix (separate task).
- Virtualization for large history lists.
- Mobile bottom sheet.

**Status: COMPLETED — 2026-05-15**

## Delivery Notes

- QA: PASS WITH FINDINGS — visual inspection confirmed one-column layout, drop zone hero, animated preview slot, trash icon, compact history, and confirm-before-apply flow all working.
- Review: SHIP WITH NOTES — `error-text` class used consistently; `view-card` framing restored across all sections.
- Fix cycles: 2 — (1) restored page header and view-card section backgrounds stripped during chrome removal; (2) merged header + drop zone into unified gradient hero card matching app aesthetic.
