# UX Spec v1 (GUI-first workflow)

## Product intent

The interface is the user's primary interaction surface. The user should feel they are operating a modern finance workspace with clear workflows for setup, import, review, and daily visibility.
The system must boot from zero data files; workspace initialization is a first-class GUI workflow.
The plain-text accounting model is an implementation detail in the default path, not the primary story the UI tells.

## Information architecture

- `/setup`: first-contact onboarding and workspace readiness checks.
- `/`: operational home dashboard.
- `/import`: import inbox, parse preview, conflict-aware apply.
- `/unknowns`: categorization queue for transactions that still need a category.

## Screen specs

### 1) Setup (`/setup`)

Purpose:
- Get a new user from zero to first successful import preview.

Sections:
- Welcome panel with a single primary CTA.
- Workspace bootstrap form:
  - workspace path
  - workspace name
  - base currency
  - start year
  - optional institution templates
- Existing workspace selector:
  - select an existing workspace path containing `settings/workspace.toml`
- Active workspace status summary:
  - institutions configured
  - years loaded
  - statements waiting

Primary actions:
- `Create Workspace` for first-time initialization.
- `Select Workspace` to attach an existing workspace.
- `Go to Import` and `Go to Unknowns` when ready.

### 2) Home (`/`)

Purpose:
- Daily finance command center.

Sections:
- Hero with concise summary and primary actions.
- Financial snapshot cards:
  - cash and credit summary
  - net worth summary
  - current-month income vs expense
- Attention queue:
  - statements waiting to import
  - unresolved review work
  - recent conflicts or notable changes
- Quick links to import, categorization, and drill-down reporting.
- Until richer reporting data exists, placeholder states should still speak in finance-first language rather than system health language.

### 3) Import (`/import`)

Purpose:
- Safely import institution CSVs with idempotent outcomes.

Sections:
- Candidate inbox table/card list.
- Import configuration card (selected statement, year, institution).
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
- Manual path editing exists only as an advanced fallback, not the primary workflow.

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
