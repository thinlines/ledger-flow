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
- Import-account add/edit flow after workspace bootstrap

Important limitations in the current baseline:

- balance and net-worth views depend on imported journal history; opening balances are not yet a first-class workflow
- the product model is still centered on configured import accounts rather than a broader account inventory
- the main navigation is still a compact top bar suited to the current route set, not the next stage of the product
- ongoing account management still lives mostly inside setup instead of a dedicated account-management surface

The current matching model is intentionally limited. That is acceptable for now.

## Experience North Star

Ledger Flow should feel like a polished personal finance application, not a frontend for plaintext accounting.

That means:

- The user should be able to import, review, monitor, and understand their finances without learning about journals, postings, or workspace files
- The overview should be trustworthy enough to support real decisions, especially for balances and net worth
- Users should be able to add accounts incrementally over time, including unsupported institutions and backfilled history, without breaking workflow
- Import and unknown matching are important support loops, but they should not define the app's identity
- The plain-text foundation remains a real product advantage, but it is a secondary concern in the primary UI
- Technical details should move into advanced or diagnostic affordances instead of dominating the default path

## Product Direction

The current goal is to make the overview trustworthy and to turn account management into a first-class part of the product without losing the momentum of the new dashboard-first posture.

That means:

- setup should continue to get the user from zero to first imported activity with minimal exposed implementation detail
- account management should support eventual consistency:
  - users can add accounts later
  - users can set opening balances before they have full history
  - users can backfill older years over time without invalidating the current picture
- the dashboard should remain the daily landing page and answer:
  - Where do I stand right now?
  - What needs my attention?
  - What changed recently?
  - How complete and trustworthy is the current balance picture?
  - If I am caught up, what should I notice or decide next?
- the rest of the product should support that overview instead of pulling users back into setup or configuration detail unnecessarily
- navigation should evolve into a sectioned finance workspace as the feature surface grows

When the books are current, the app should not feel "done" in a dead-end sense.
It should switch from maintenance mode into guidance mode:

- reassure the user that their books are current
- surface meaningful changes, trends, and outliers
- help the user spot decisions worth making without forcing a full budgeting workflow

## UI Principles

- Show financial outcomes first, workflow state second, and technical details last.
- Keep one dominant action above the fold; secondary actions should be sparse and obvious.
- Use overview screens to summarize, not to explain internals.
- Hide paths, ledger-account mappings, and other advanced details unless the user explicitly needs them.
- Separate first-run setup from ongoing account management, even if setup remains the first place users encounter accounts.
- Prefer stable mental models: an account can exist before it has import automation or complete historical coverage.
- Reward a caught-up state with insight and confidence, not just the absence of work.

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
- more polished review handoff and per-account status details
- clearer handoff from setup into ongoing account management
- keep setup focused on momentum rather than turning it into the long-term home for account administration

Scope:

- Turn setup into a staged, resumable workflow instead of a single long form
- Reduce upfront decisions by defaulting workspace details and hiding advanced settings
- Move ledger-account and file-path details out of the primary path
- Keep first import closely connected to setup instead of requiring an early screen jump
- Show clear progress, readiness states, and post-import next actions
- Hand off into overview, review, or accounts work without requiring the user to understand internals

Expected outcome:

- First-run feels like a consumer finance app, not a bootstrap tool
- Users can get to first useful result without understanding internal storage structure
- The app's safe import model remains intact while setup becomes easier to complete

### 1. Account Foundation and Eventual Consistency

Make balances trustworthy and let users build a complete account inventory over time instead of only through preconfigured import accounts.

Current status:

- import accounts can be added and edited after workspace bootstrap
- the dashboard derives balances from journal activity for configured import accounts
- eventual consistency is already a product principle, but the product model is still too import-centric for that principle to be fully usable

Remaining scope:

- opening balance workflow and persistence
- manual or unsupported institution path
- dedicated accounts overview and management screen
- clearer distinction between tracked accounts and import configuration
- add/delete/archive/reorder account management as appropriate
- account-level completeness and status cues

Scope:

- Let users create tracked accounts even when no importer exists yet
- Support setting and editing opening balances so balances and net worth are meaningful before full historical backfill
- Separate the real-world account inventory from import/parser configuration
- Show all accounts in a dedicated Accounts area with names, balances, status, and edit actions
- Allow users to add more accounts later without relying on setup as the only management surface
- Preserve backfillability: older years can be imported later without breaking the current financial picture

Expected outcome:

- Users can adopt the product incrementally instead of needing complete importer coverage up front
- Unsupported institutions no longer block adoption
- The overview can become trustworthy for balances and net worth, not only spending activity

### 2. Navigation, Framing, and App Shell

Keep the product finance-first while moving from a compact route list to a shell that can support a broader workspace.

Current status:

- the app shell, overview copy, and home screen hierarchy are now finance-first instead of status-first
- workspace-path and version detail no longer dominate the main home screen
- the current top navigation works for the present route set but will become crowded as accounts and reporting grow

Scope:

- Move from a flat top nav to a sidebar or other sectioned shell when the account surface lands
- Group the product into clear areas such as Overview, Accounts, Import or Activity, Review, Automation, and Setup
- Keep daily-use workflows prominent while moving setup/admin flows into secondary sections
- Continue moving file paths, journal terminology, and other implementation details into secondary or advanced UI
- Improve empty states, success states, and handoff moments so the product feels polished instead of tool-like

Expected outcome:

- The product reads as a coherent finance workspace rather than a growing list of routes
- New capabilities can land without making navigation noisy or ambiguous

### 3. Dashboard and Financial Visibility

Build a dashboard that surfaces financial state instead of mostly system state.

Current status:

- `/` now shows net worth, tracked balances, six-month cash flow, category movement, recent transactions, and action cues
- the home screen is useful even when the user is not actively importing
- overview data comes from a dedicated dashboard API instead of only app-state counts
- balance-oriented metrics are only as trustworthy as the current account completeness and starting-balance support

Scope:

- Cash and credit snapshot
- Net worth summary with clear account coverage
- Income vs expense for the current month
- Spending by category
- Recent transactions
- Unresolved unknown-count and review backlog
- Import inbox and latest import activity
- Clear cues when balances are partial or depend on missing opening-balance or backfill work

Expected outcome:

- The home screen becomes useful even when the user is not importing files
- The user can quickly see whether books are current, what needs action, and how trustworthy the current balance picture is

### 4. Reporting Foundation

Add the backend support needed to power the dashboard and future reporting screens.

Current status:

- balance summaries for tracked accounts are implemented
- current-month income/spending and six-month cash flow are implemented
- category totals for month-over-month comparison are implemented
- recent transaction query support is implemented through the overview API

Remaining scope:

- richer date-range controls
- drill-down queries from dashboard cards into filtered activity views
- more complete reporting for manual or non-import accounts and longer historical analysis
- lightweight metrics for account completeness, review backlog, and import history

Scope:

- Balance summaries by account and account group
- Income and expense rollups by month
- Category totals for configurable date ranges
- Recent transaction query support
- Import history, review backlog, and account completeness metrics

Expected outcome:

- Dashboard data comes from explicit API endpoints instead of ad hoc page logic
- Future reporting work and account insights can build on a stable backend shape

### 5. Workflow Integration and Daily Use

Once setup, accounts, and dashboard visibility exist, tighten the links between screens.

Current status:

- setup now keeps the first import inline and can hand off to review or overview
- the broader daily-use loop still needs tighter continuity between overview, accounts, import, review, and automation

Scope:

- Better handoff from import results to unknown review
- Dashboard links into concrete work queues
- Clearer "what changed" summaries after import and review actions
- Better movement between accounts, import, and overview once account management is first-class
- More useful home-page cues for stale inbox files, unresolved unknowns, and recent conflicts

Expected outcome:

- The app feels like one continuous workflow rather than separate tools

### 6. All-Caught-Up Experience and Financial Guidance

Once maintenance tasks are clear and the balance picture is trustworthy, the product should still provide value.

Scope:

- Better "all caught up" states on the dashboard hero and next-action areas
- "Since last check-in" summaries that explain what changed since the user last opened the app
- Stronger monthly progress framing: income, spending, savings, and net-worth movement against recent history
- More interpretable movement summaries for categories, merchants, and recurring charges
- Lightweight anomaly cues such as unusual large spend, rising category pressure, or low-cash/high-credit warnings when the data supports them
- Gentle guidance prompts that help the user decide what to review or adjust next without turning the product into a budgeting suite

Recommended progression inside this theme:

- Start with recurring monthly charges, subscription visibility, and annual-renewal awareness
- Add baseline spending views so the user can understand their real fixed and semi-fixed cost structure
- Add savings-rate trend and monthly surplus framing so the app begins to connect bookkeeping to financial progress
- Add lightweight stability goals such as "month ahead" and emergency-fund progress before attempting a full budget workflow
- Treat these as guidance and visibility layers, not as a full planning system

Near-term candidate features:

- recurring charge detection and a dedicated dashboard/home card
- "cost of being me" or fixed-monthly-obligations summary
- recurring-spend increases and cancellation opportunities
- monthly surplus and savings-rate trend line
- lightweight financial health prompts tied to available data

Non-goals within this priority:

- full zero-based budgeting or envelope budgeting
- long-horizon FI calculators with portfolio-growth assumptions
- retirement drawdown modeling
- goals/planning systems that require heavy new data entry

Expected outcome:

- Opening the app feels useful even when there is no maintenance queue
- The product helps users understand and steer finances, not only keep books current
- The dashboard becomes a place for reassurance, awareness, and lightweight decision support

## Deferred for Now

These are valid ideas, but they are not current priorities:

- Merchant management UI
- Expanding the rule language beyond the current limited matching model
- Full budgeting system
- Zero-based/envelope budgeting workflow
- Long-range forecasting and goals
- Detailed FI planner with retirement-timeline modeling
- Advanced reconciliation features beyond the current safe-edit workflow

## Milestone Outline

### Milestone A: Setup Revamp

- Rework `/setup` into a guided first-run flow with visible progress
- Make workspace path and destination-account details advanced by default
- Keep first import embedded in the setup journey where possible
- Improve completion states and direct handoff into overview, review, or accounts work

Current status:

- the core staged setup flow and inline first import are implemented
- milestone completion now depends on polish and handoff, not core architecture

Definition of done:

- A new user can complete setup and a first import without needing ledger terminology
- Setup feels like one continuous workflow instead of multiple disconnected tools
- The product presents financial next steps before implementation details
- Setup is no longer the only place where ongoing account management lives

### Milestone B: Account Foundation and Eventual Consistency

- Add opening-balance support
- Add a manual or unsupported-account path
- Separate tracked accounts from import configuration
- Add a dedicated Accounts screen with add, view, and edit flows

Current status:

- post-bootstrap import-account add/edit exists
- milestone completion now depends on broadening from import accounts to a durable account inventory

Definition of done:

- A user can add and track an account even without a supported importer or complete history
- Balances can be seeded with opening values and refined later
- The account inventory can be viewed and edited outside setup
- Eventual consistency is reflected in real product workflows, not only in project principles

### Milestone C: Navigation and App Shell

- Move from a flat top nav to a sectioned shell or sidebar
- Group related workflows by purpose
- Keep daily finance work primary and setup/admin work secondary

Current status:

- the finance-first shell and framing are already in place
- remaining work is structural scalability, not copy direction

Definition of done:

- Navigation scales cleanly beyond the current route set
- Users can discover accounts, import, review, automation, and setup without crowding or ambiguity

### Milestone D: Dashboard and Reporting

- Keep the dashboard as the main daily landing page
- Add trust and completeness cues for balances
- Add drill-down paths and date-range support
- Extend reporting to broader account coverage

Current status:

- the overview dashboard and supporting API are implemented
- remaining work is trust/completeness, drill-down, and expanded reporting depth

Definition of done:

- A user can see account state, recent activity, and pending work without opening other screens first
- Dashboard numbers remain interpretable even when history is incomplete
- The dashboard is not just summary-only; it can lead the user to the underlying data

### Milestone E: Workflow Cohesion

- Tighten import-to-review navigation
- Surface post-import and post-review outcomes more clearly
- Make account management part of the daily loop instead of a side path

Definition of done:

- The common personal-finance loop is smooth: import, review, confirm, monitor, and adjust accounts

### Milestone F: All-Caught-Up Guidance

- Add a meaningful "all caught up" hero state with reassurance plus useful next insight
- Surface "since last check-in" changes and monthly progress summaries
- Highlight trends, anomalies, and recurring-spend changes that deserve attention even when nothing is blocked
- Launch recurring-charge visibility as the first guidance feature beyond maintenance
- Add savings-rate and baseline-spending cues before considering broader planning features

Definition of done:

- A user with no pending import or review work still gets clear value from opening the dashboard
- The home screen helps the user understand what changed and what may deserve a decision next
- The product feels like a finance app, not just a maintenance queue

## Notes

- Preserve the current safe import semantics and append-oriented journal workflow
- Eventual consistency applies to both historical imports and account coverage, not only import years
- Opening balances and account completeness are prerequisites for trustworthy balance-driven guidance
- Avoid broad matching-system expansion unless dashboard work reveals a concrete need
- Prefer features that increase visibility and confidence over features that add planning complexity
- Lightweight guidance is in scope; full planning systems are not
- Do not surface ledger/journal terminology in primary UI copy unless there is no clearer user-facing term
