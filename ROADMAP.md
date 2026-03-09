# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

## Current Baseline

The app already has a usable bookkeeping workflow:

- Finance-first overview dashboard with net worth, tracked balances, cash flow, category movement, recent transactions, and action cues
- Workspace setup and selection
- Staged setup flow with workspace-first creation, post-bootstrap account setup, and inline first import
- CSV import with preview, duplicate detection, conflict detection, and safe apply
- Unknown transaction review with staged account assignment
- Reusable match rules with ordered evaluation
- Inline account creation during review and rule authoring

The current matching model is intentionally limited. That is acceptable for now.

## Experience North Star

Ledger Flow should feel like a polished personal finance application, not a frontend for plaintext accounting.

That means:

- The user should be able to import, review, monitor, and understand their finances without learning about journals, postings, or workspace files
- Import and unknown matching are important support loops, but they should not define the app's identity
- The plain-text foundation remains a real product advantage, but it is a secondary concern in the primary UI
- Technical details should move into advanced or diagnostic affordances instead of dominating the default path

## Product Direction

The current goal is to deepen the app's new dashboard-first posture without destabilizing the existing import and review flow.

That means:

- setup should continue to get the user from zero to first imported activity with minimal exposed implementation detail
- the dashboard should remain the daily landing page and answer:
  - Where do I stand right now?
  - What needs my attention?
  - What changed recently?
- the rest of the product should support that overview instead of pulling users back into configuration detail unnecessarily

## UI Principles

- Show financial outcomes first, workflow state second, and technical details last.
- Keep one dominant action above the fold; secondary actions should be sparse and obvious.
- Use overview screens to summarize, not to explain internals.
- Hide paths, ledger-account mappings, and other advanced details unless the user explicitly needs them.

Merchant management remains desirable, but it is not an active priority right now.

## Priorities

### 0. Setup and First-Run Flow

Revamp setup so new users reach first imported activity with less friction and better momentum.

Current status:

- `/setup` is now a staged flow instead of a single long form
- Workspace creation and tracked-account setup are separated
- First import can be completed inside setup with the same preview/apply safety model used on `/import`
- App state now exposes setup progress such as account readiness, first-import status, and review follow-up

Remaining scope:

- stronger post-import completion summary inside setup
- delete/reorder account management
- manual or unsupported institution path
- more polished review handoff and per-account status details

Scope:

- Turn setup into a staged, resumable workflow instead of a single long form
- Reduce upfront decisions by defaulting workspace details and hiding advanced settings
- Move ledger-account and file-path details out of the primary path
- Keep first import closely connected to setup instead of requiring an early screen jump
- Show clear progress, readiness states, and post-import next actions

Expected outcome:

- First-run feels like a consumer finance app, not a bootstrap tool
- Users can get to first useful result without understanding internal storage structure
- The app's safe import model remains intact while setup becomes easier to complete

### 1. Product Framing and App Shell

Reposition the current UI so the app reads as a finance workspace before the full dashboard exists.

Current status:

- the app shell, overview copy, and home screen hierarchy are now finance-first instead of status-first
- workspace-path and version detail no longer dominate the main home screen
- next actions are surfaced as an attention queue rather than scattered status widgets

Scope:

- Rework navigation, home-page framing, and cross-screen copy around financial tasks and outcomes
- Move file paths, journal terminology, and other implementation details into secondary or advanced UI
- Improve empty states, success states, and handoff moments so the product feels polished instead of tool-like

Expected outcome:

- The app no longer appears to be only an import-and-matching utility
- Even before reporting lands, the product feels like a coherent finance workspace

### 2. Dashboard and Financial Visibility

Build a dashboard that surfaces financial state instead of mostly system state.

Current status:

- `/` now shows net worth, tracked balances, six-month cash flow, category movement, recent transactions, and action cues
- the home screen is useful even when the user is not actively importing
- overview data comes from a dedicated dashboard API instead of only app-state counts

Scope:

- Cash and credit snapshot
- Net worth summary
- Income vs expense for the current month
- Spending by category
- Recent transactions
- Unresolved unknown-count and review backlog
- Import inbox and latest import activity

Expected outcome:

- The home screen becomes useful even when the user is not importing files
- The user can quickly see whether books are current and what needs action

### 3. Reporting Foundation

Add the backend support needed to power the dashboard and future reporting screens.

Current status:

- balance summaries for tracked accounts are implemented
- current-month income/spending and six-month cash flow are implemented
- category totals for month-over-month comparison are implemented
- recent transaction query support is implemented through the overview API

Remaining scope:

- richer date-range controls
- drill-down queries from dashboard cards into filtered activity views
- more complete reporting for non-import accounts and longer historical analysis

Scope:

- Balance summaries by account and account group
- Income and expense rollups by month
- Category totals for configurable date ranges
- Recent transaction query support
- Lightweight metrics for review backlog and import history

Expected outcome:

- Dashboard data comes from explicit API endpoints instead of ad hoc page logic
- Future reporting work can build on a stable backend shape

### 4. Workflow Integration and Daily Use

Once dashboard visibility exists, tighten the links between screens.

Scope:

- Better handoff from import results to unknown review
- Dashboard links into concrete work queues
- Clearer "what changed" summaries after import and review actions
- More useful home-page cues for stale inbox files, unresolved unknowns, and recent conflicts

Expected outcome:

- The app feels like one continuous workflow rather than separate tools

## Deferred for Now

These are valid ideas, but they are not current priorities:

- Merchant management UI
- Expanding the rule language beyond the current limited matching model
- Budgeting
- Forecasting and goals
- Advanced reconciliation features beyond the current safe-edit workflow

## Milestone Outline

### Milestone A: Setup Revamp

- Rework `/setup` into a guided first-run flow with visible progress
- Make workspace path and destination-account details advanced by default
- Keep first import embedded in the setup journey where possible
- Improve completion states and direct handoff into overview or review work

Current status:

- the core staged setup flow and inline first import are implemented
- milestone completion now depends on polish and completion-state work rather than core architecture

Definition of done:

- A new user can complete setup and a first import without needing ledger terminology
- Setup feels like one continuous workflow instead of multiple disconnected tools
- The product presents financial next steps before implementation details

### Milestone B: Dashboard MVP

- Reframe the app shell and home-page copy around financial awareness instead of system status
- Add backend endpoints for balances, category totals, recent transactions, and queue metrics
- Replace the current home page metrics with financial summaries
- Add date-range controls where needed, while keeping the default view simple

Current status:

- the overview dashboard, supporting API, and finance-first app-shell framing are implemented
- remaining work is expansion and drill-down polish, not the core home-screen architecture

Definition of done:

- The dashboard is the main daily landing page
- A user can see account state, recent activity, and pending work without opening other screens first
- Primary UI language talks about finances and activity, not ledger internals

### Milestone C: Reporting and Drill-Down

- Add drill-down paths from dashboard cards into filtered transaction views or existing workflows
- Add month-over-month summaries for spending and income
- Improve category visibility enough to spot anomalies and trends

Definition of done:

- The dashboard is not just summary-only; it can lead the user to the underlying data

### Milestone D: Workflow Cohesion

- Tighten import-to-review navigation
- Surface post-import outcomes more clearly
- Make the review queue easier to revisit from the dashboard

Definition of done:

- The common personal-finance loop is smooth: import, review, confirm, and monitor

## Notes

- Preserve the current safe import semantics and append-oriented journal workflow
- Avoid broad matching-system expansion unless dashboard work reveals a concrete need
- Prefer features that increase visibility and confidence over features that add planning complexity
- Do not surface ledger/journal terminology in primary UI copy unless there is no clearer user-facing term
