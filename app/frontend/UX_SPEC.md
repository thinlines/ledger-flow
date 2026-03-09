# UX Spec v1 (GUI-first workflow)

## Product intent

The interface is the user's primary interaction surface. The user should feel they are operating a modern finance workspace with clear workflows for setup, import, review, and daily visibility.
The system must boot from zero data files; workspace initialization is a first-class GUI workflow.
The plain-text accounting model is an implementation detail in the default path, not the primary story the UI tells.

## Interface rules

- Lead with financial outcomes, not setup detail or system metadata.
- Limit each screen to one dominant decision at a time.
- Keep advanced configuration hidden by default and reachable by explicit reveal.
- Prefer summaries and action cues over dense diagnostic readouts.
- Keep technical language out of primary UI copy unless there is no better user-facing term.

## Information architecture

- `/setup`: first-contact onboarding and workspace readiness checks.
- `/`: operational home dashboard.
- `/import`: import inbox, parse preview, conflict-aware apply.
- `/unknowns`: review queue for transactions that still need a category.

## Screen specs

### 1) Setup (`/setup`)

Purpose:
- Get a new user from zero to first useful financial activity, not just a completed config form.
- Default to creating a new workspace; connecting an existing one is secondary.
- Keep the first import tightly connected to setup so momentum is not lost.

Current implementation status:
- Implemented as a staged flow with `Welcome`, `Workspace`, `Accounts`, and `First Import`.
- Workspace creation and account setup are now separate steps.
- First import uses the shared import workflow directly inside setup, with `/import` retained as the full import workspace.

Structure:
- Resumable checklist or staged flow, not one long form.
- Clear progress indicator with 4 core steps:
  - Welcome
  - Workspace
  - Accounts
  - First Import

Sections:
- Welcome panel with a single primary CTA and short explanation of what happens next.
- Workspace basics:
  - workspace name
  - base currency
  - advanced reveal for workspace path and start year
- Accounts to track:
  - institution
  - account display name
  - optional last4
  - advanced reveal for destination ledger account
- First import:
  - upload or choose statement
  - choose target account if needed
  - preview import
  - apply import
- Existing workspace selector:
  - available through a secondary reveal or alternate path
  - select an existing workspace path containing `settings/workspace.toml`
- Completion summary:
  - accounts configured
  - statements imported
  - items needing review

Primary actions:
- `Create Workspace` for first-time initialization.
- `Continue` between setup steps when state is sufficient.
- `Preview Import` and `Apply Import` without leaving setup.
- `Open Overview` and `Review Categories` once setup is complete.

Behavior:
- Hide file-path and ledger-account details by default.
- Auto-suggest destination account paths from the chosen institution/account name.
- Permit creating the workspace before all accounts are entered.
- Prefer account name as the primary label; institution is supporting context.
- If unknowns remain after first import, setup should direct the user into review with clear counts.

### 2) Home (`/`)

Purpose:
- Daily finance command center.
- The dominant question is: what should I do next?

Current implementation status:
- Implemented as a finance-first overview dashboard.
- The primary screen now emphasizes net worth, balances, cash flow, category movement, recent transactions, and action cues.
- Workspace-path and version details are intentionally absent from the main home screen.

Sections:
- Hero with net-worth emphasis, freshness context, and a single dominant CTA.
- Financial snapshot cards:
  - tracked balances
  - current-month cash flow
  - current-month income
  - current-month spending
- Balances section:
  - tracked account list
  - account type and masked last4 as supporting context
- Attention queue:
  - statements waiting to import
  - unresolved review work
  - setup steps still blocking the dashboard
- Cash-flow section:
  - six-month income/spending rows
  - current-month net indicator
- Category section:
  - current month versus previous month by category
- Recent activity section:
  - latest transactions
  - category and account context
- At most two secondary actions above the fold.
- If setup is incomplete, the home page should pivot into a staged progress view rather than exposing raw configuration data.

### 3) Import (`/import`)

Purpose:
- Safely import account-linked CSVs with idempotent outcomes.
- Serve as both the standalone import workspace and the reusable flow embedded in setup.

Sections:
- Candidate inbox table/card list.
- Import configuration card (selected statement, year, import account).
- Preview result card:
  - New / Duplicate / Conflict counts
  - sample rendered transactions
- Apply result card:
  - appended count
  - skipped duplicate count
  - conflict list

Behavior:
- Candidate click pre-fills settings.
- Preview required before apply.
- Apply button disabled during in-flight operation.
- Import account selection is the primary choice; institution is supporting context.
- Manual path editing exists only as an advanced fallback, not the primary workflow.
- The same interaction model should remain visually consistent whether rendered on `/import` or inside `/setup`.

### 4) Unknowns (`/unknowns`)

Purpose:
- Resolve uncategorized transaction mappings quickly.

Sections:
- Detected year/journal selection input with dropdown suggestions.
- Scan summary card (group count, transaction count).
- Group cards per payee with inline account assignment.
- Stage/apply action bar.
- Result card with updated count, learned rule count, warnings.

Behavior:
- Suggested account prefill when available.
- Stage first, then apply.
- Detected journals/years are the primary entry point; direct path entry is an advanced fallback.

## Visual system

- Typography: `Space Grotesk` for headings, `Inter` for body.
- Palette:
  - background gradient: cool neutral + mint tint
  - primary: deep blue-green
  - accent: amber for attention, red for errors
- Components:
  - elevated cards with soft borders/shadows
  - rounded controls (`10px`)
  - status pills (`healthy`, `warning`, `error`, `neutral`)
  - prominent primary buttons and subtle secondary buttons
- Responsive:
  - desktop: card grids
  - mobile: single-column stacking with full-width controls

## Content style

- Outcome-oriented labels: "Preview Import", "Apply", "Resolve".
- Talk about finances, categories, recent activity, and next steps before talking about files or internals.
- Avoid implementation details in primary UI copy.
- Keep technical details available in secondary text/expanders.

## Accessibility baseline

- Keyboard reachable actions.
- Contrast-safe status colors.
- Visible focus states on interactive controls.
