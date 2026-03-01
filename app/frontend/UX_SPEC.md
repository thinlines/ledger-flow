# UX Spec v1 (GUI-first workflow)

## Product intent

The interface is the user's primary interaction surface. The user should feel they are operating a modern finance workspace with clear workflows for setup, import, and review.
The system must boot from zero data files; workspace initialization is a first-class GUI workflow.

## Information architecture

- `/setup`: first-contact onboarding and workspace readiness checks.
- `/`: operational home dashboard.
- `/import`: import inbox, parse preview, conflict-aware apply.
- `/unknowns`: reconciliation queue for unknown account assignments.

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
  - journals discovered
  - inbox files discovered

Primary actions:
- `Create Workspace` for first-time initialization.
- `Select Workspace` to attach an existing workspace.
- `Go to Import` and `Go to Unknowns` when ready.

### 2) Home (`/`)

Purpose:
- Daily command center.

Sections:
- Hero with concise summary and primary actions.
- Health and workflow status cards:
  - service health
  - import queue size
  - journal coverage
  - unresolved review queue hint
- Quick links to Import and Unknowns.

### 3) Import (`/import`)

Purpose:
- Safely import institution CSVs with idempotent outcomes.

Sections:
- Candidate inbox table/card list.
- Import configuration card (path, year, institution).
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

### 4) Unknowns (`/unknowns`)

Purpose:
- Resolve unknown account mappings quickly.

Sections:
- Journal selection input with dropdown suggestions.
- Scan summary card (group count, transaction count).
- Group cards per payee with inline account assignment.
- Stage/apply action bar.
- Result card with updated count, learned rule count, warnings.

Behavior:
- Suggested account prefill when available.
- Stage first, then apply.

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
- Avoid implementation details in primary UI copy.
- Keep technical details available in secondary text/expanders.

## Accessibility baseline

- Keyboard reachable actions.
- Contrast-safe status colors.
- Visible focus states on interactive controls.
