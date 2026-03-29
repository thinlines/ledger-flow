# ImportFlow Component Decomposition Plan

The import flow component (`app/frontend/src/lib/components/ImportFlow.svelte`)
is 1708 lines with workflow state management, preview display, inbox
management, and import history all in one file. This plan breaks it into
focused components and modules, designed to be executed incrementally.

## Current structure

```
Script block:   ~526 lines (types, 21 state vars, 25 functions)
Template block:  ~710 lines
Style block:     ~472 lines
```

The template is the largest section because the component renders two
substantially different layouts — a setup-mode vertical flow and a standalone
two-column layout — with significant markup duplication between them.

### Concerns identified in the script block

| # | Concern                       | Lines (approx) | Key functions                                                  |
|---|-------------------------------|----------------:|----------------------------------------------------------------|
| 1 | Types (local)                 |             40 | Candidate, ImportAccountOption, ImportHistoryEntry, etc.        |
| 2 | File/account selection        |             50 | `setImportAccount`, `setYear`, `onStatementFileChange`, `setSelectedPath`, `clearSelectedFile` |
| 3 | Preview generation            |             80 | `uploadAndPreviewFile`, `runPreview`, `importResultAction`, `primaryActionLabel` |
| 4 | Import execution              |             30 | `applyStage`                                                   |
| 5 | Inbox management              |             40 | `pickCandidate`, `removeSelectedCandidate`                     |
| 6 | Import history & undo         |             50 | `undoHistoryEntry`                                             |
| 7 | Error handling & recovery     |             70 | `sendImportRequest`, `parseApiFailure`, `parseImportRecovery`, `resetImportState` |
| 8 | Data loading & sync           |             60 | `loadImportData`, `onMount`, refreshToken watcher              |
| 9 | Display helpers               |             30 | `pathLabel`, `optionalPathLabel`, `accountLabel`, `formatDateTime`, `errorMessage`, `statementStatusNote`, `currentStatementLabel` |

### Template sections

| Section                        | Rough lines | Notes                                    |
|--------------------------------|------------:|-----------------------------------------|
| Setup-mode workflow card       |         180 | Vertical flow with account/year/file selection + inbox |
| Setup-mode preview card        |          85 | Preview results for setup mode           |
| Standalone workflow card       |         250 | Two-column layout with workflow + sidebar |
| Standalone preview panel       |          95 | Preview results nested in standalone     |
| Standalone inbox sidebar       |          60 | Candidate list                           |
| Import history section         |          90 | Past imports with undo                   |

The setup-mode and standalone-mode sections share substantial structure
(account selector, year selector, file upload, inbox list, preview display)
but are rendered as separate template blocks with duplicated markup.

## Extraction plan

Each step is an independent, shippable unit.

### Step 1: Extract types → `$lib/types/import.ts`

Move local type aliases (`Candidate`, `ImportAccountOption`,
`ImportHistoryEntry`, `ImportPreview`, `ImportRecoveryState`) into a shared
type file.

**Risk:** None. Pure type movement.
**Test:** `pnpm check` passes.

### Step 2: Extract import API helpers → `$lib/import-api.ts`

Move `sendImportRequest`, `parseApiFailure`, `parseImportRecovery`, and
`errorMessage` into a module. These are the HTTP/error-handling primitives
that other import functions build on.

`sendImportRequest` currently sets `recoveryState` and `error` as side
effects — refactor it to return a result object and let the caller update
state. This makes the module testable and decouples it from component
state.

**Risk:** Low. Straightforward signature change.
**Test:** `pnpm check` passes.

### Step 3: Extract display helpers → `$lib/import-display.ts`

Move `pathLabel`, `optionalPathLabel`, `accountLabel`, `formatDateTime`
into a shared module. These are pure functions used across the template.

`currentStatementLabel`, `statementStatusNote`, `primaryActionLabel`, and
`importResultAction` also move — they're pure functions of preview/selection
state once their dependencies are passed as arguments.

**Risk:** None. Pure functions.
**Test:** `pnpm check` passes.

### Step 4: Extract import history section → `ImportHistory.svelte`

Create `$lib/components/ImportHistory.svelte` containing:
- The history section template (past imports list, undo buttons, details)
- `undoHistoryEntry` logic (dispatches events for state the parent owns)
- History-specific state: receives `historyEntries` and `historyMessage`
  as props

Props: `historyEntries`, `historyMessage`, `loadingState`.
Events: `undo` (parent handles API call and state update).

**Risk:** Low. Self-contained display section.
**Test:** `pnpm check` passes. Manual test of history display and undo.

### Step 5: Extract inbox/candidates list → `ImportInbox.svelte`

Create `$lib/components/ImportInbox.svelte` containing:
- The candidate list template (used in both setup and standalone modes —
  this eliminates the markup duplication)
- `pickCandidate` and `removeSelectedCandidate` dispatch as events

Props: `candidates`, `selectedPath`, `loadingState`.
Events: `pick`, `remove`.

**Risk:** Low. The two duplicate inbox renders collapse into one component
used in both modes.
**Test:** `pnpm check` passes. Manual test of candidate selection and
removal in both setup and standalone modes.

### Step 6: Extract preview display → `ImportPreview.svelte`

Create `$lib/components/ImportPreview.svelte` containing:
- The preview results template (summary stats, sample list, conflict
  warnings, recovery state display)
- `importResultAction` for determining follow-up CTA

Props: `preview`, `recoveryState`, `loadingState`.
Events: `apply`, `cancel`.

This eliminates the second piece of template duplication — the preview
section rendered in both setup and standalone modes.

**Risk:** Low. Read-only display with two event dispatches.
**Test:** `pnpm check` passes. Manual test of preview display with new,
duplicate, conflict, and unknown transactions.

### Step 7: Unify setup/standalone layout (optional)

After steps 5–6, the setup and standalone modes share the same child
components. The remaining difference is layout (single-column vs
two-column). Consider merging the two template branches into one layout
that switches between grid configurations based on a `mode` prop,
eliminating the last source of duplication.

This step is optional — it's a polish improvement, not a maintainability
necessity.

## Expected outcome

After steps 1–6:

| Artifact                       | Lines (est) |
|--------------------------------|------------:|
| `ImportFlow.svelte`            |    600–750  |
| `$lib/types/import.ts`         |          40 |
| `$lib/import-api.ts`           |          80 |
| `$lib/import-display.ts`       |          60 |
| `ImportHistory.svelte`         |     150–180 |
| `ImportInbox.svelte`           |     100–130 |
| `ImportPreview.svelte`         |     150–180 |

The component drops from 1708 to ~650 lines. The template duplication
between setup and standalone modes is eliminated via shared child
components.

## Execution guidance

- **One step per task.** Each extraction is a self-contained commit.
- **No behavior changes.** Every step is a pure refactor.
- **Opportunistic attachment.** When a feature task touches import flow,
  perform the most relevant extraction step first.
- **Steps 5–6 have the highest impact.** They eliminate template
  duplication and should be prioritized if the component is being modified.
- **Verify after each step:** `pnpm check` must pass. Test both setup and
  standalone import modes.
