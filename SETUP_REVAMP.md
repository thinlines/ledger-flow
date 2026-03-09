# Setup Revamp Plan

This document turns the current setup research into an implementation-ready plan.
It is intended to guide product, UX, and engineering work for the next setup revamp.

## Implementation Status

Implemented so far:

- staged setup shell with welcome, workspace, accounts, and first-import steps
- workspace creation separated from tracked-account setup
- post-bootstrap import-account add/edit flow
- setup progress state from `/api/app/state`
- first import embedded directly in setup using the shared preview/apply flow

Still remaining:

- stronger completion summary after first import
- delete or reorder account management
- manual or unsupported institution path
- richer per-account status and review handoff polish

## Why Setup Needs to Change

Ledger Flow already has a safe import engine and a credible review workflow.
The problem is the first-run experience.

Today the user is asked to think about:

- workspace path
- base currency
- start year
- institution template choice
- ledger account naming

before they have seen any financial value.

Commercial personal finance apps usually do the opposite:

- establish trust and momentum first
- ask only for the minimum needed to start
- frame setup as a checklist, not a form dump
- get the user to connected accounts or first imported history quickly
- show progress and immediate payoff after each step

Ledger Flow should borrow that pacing while keeping its current import safety model.

## Product Positioning

Ledger Flow setup should feel like:

- a guided first-run flow
- resumable and non-destructive
- finance-first in language and outcomes
- local-first in implementation, but not in primary copy

It should not feel like:

- a one-shot configuration wizard
- a plaintext accounting bootstrap tool
- a prerequisite wall before the app becomes useful

## Design Principles

1. Reduce upfront decisions.
Default aggressively. Hide advanced settings until the user needs them.

2. Move from form-first to workflow-first.
Setup should be a short sequence with visible progress and clear next actions.

3. Get to first imported activity fast.
The best setup success signal is a completed preview or import, not a completed config form.

4. Keep technical structure behind the curtain.
Workspace path, ledger account names, and file details stay secondary or advanced.

5. Preserve current safety guarantees.
Preview-before-apply, duplicate detection, conflict surfacing, and append-only import semantics remain intact.

## Previous Flow

Before the current setup slice landed, the default path was:

1. Open `/setup`
2. Create a workspace
3. Manually define import accounts
4. Go to `/import`
5. Upload statement
6. Preview import
7. Apply import
8. Go to `/unknowns`

That flow was functional, but it split the user's first-run momentum across separate screens and exposed implementation choices too early.

## Current Flow

The current shipped flow is:

1. Open `/setup`
2. Create or select a workspace
3. Add tracked accounts after bootstrap
4. Upload, preview, and apply the first import directly inside setup
5. Continue to review or overview based on setup state

This closes the biggest first-run gap, but the completion and polish work listed above is still open.

## Target Flow

Target first-run path:

1. Welcome
2. Create your finance workspace
3. Add accounts you want to track
4. Import your first statement
5. Review what needs attention
6. Finish setup and land on the overview

This should be implemented as a resumable checklist with progress, not as a single long form.

## Setup V2 Information Architecture

### Step 1: Welcome

Purpose:
- explain what Ledger Flow will help the user do next
- make `Create new workspace` the obvious primary path
- keep `Use existing workspace` available but secondary

Primary content:
- short value statement
- 3-step or 4-step checklist preview
- one primary CTA

Secondary content:
- existing workspace connection
- advanced explanation of the local/plain-text foundation

### Step 2: Workspace Basics

Purpose:
- create the workspace with as little friction as possible

Default fields:
- workspace name
- base currency

Advanced fields:
- workspace path
- start year

Behavior:
- auto-suggest a workspace path
- default currency from locale where possible
- default start year to current year
- allow creating the workspace with zero import accounts

Success state:
- show a compact "workspace ready" confirmation
- move directly into account setup

### Step 3: Accounts to Track

Purpose:
- define the real-world accounts the user cares about without forcing accounting terminology

Primary fields per account:
- institution
- account nickname
- last 4

Secondary or advanced fields per account:
- destination account path
- parser details or template diagnostics

Behavior:
- present institution templates as searchable choices or quick-add chips
- auto-generate the destination ledger account in the background
- allow multiple accounts per institution
- allow blank/manual accounts for unsupported institutions
- show account cards with clear readiness states

Per-account statuses:
- ready to import
- needs institution
- needs account name
- no statements imported yet
- activity imported

### Step 4: First Import

Purpose:
- keep onboarding momentum inside setup until the user sees real account activity

Primary experience:
- upload or choose a statement
- select the target account if needed
- preview import
- apply import

Behavior:
- reuse current preview/apply safety model
- prefill account and year from candidate detection when possible
- show the account name as the primary identity, institution as supporting context
- keep direct path entry as an advanced fallback only

Success state:
- show new, duplicate, conflict, and unknown counts
- link directly to category review if unknowns exist
- allow "Import another statement" without restarting setup

### Step 5: Finish and Handoff

Purpose:
- make the user feel the product is now useful

Completion summary:
- accounts added
- statements imported
- transactions added
- items needing review

Primary next actions:
- open overview
- review categories
- import another statement

## UX Changes Relative to Today

### What Should Move Out of the Default Path

- explicit workspace path editing
- explicit ledger account naming
- technical destination details
- file-path-centric copy
- separate screen navigation before the first import is done

### What Should Become More Visible

- progress through setup
- readiness and completion states
- "what happens next" guidance
- first-value outcomes after import
- review backlog created by the import

## Copy Direction

Preferred language:

- accounts
- statements
- activity
- categories
- ready
- review
- import

Avoid in primary copy:

- journal
- ledger account
- workspace files
- postings
- parser

These terms can exist in advanced sections, diagnostics, or developer-facing docs.

## Backend and State Implications

The current backend can bootstrap a workspace and handle imports safely, but setup v2 will need a clearer onboarding state model.

Suggested additions:

- app state flags such as `needsSetup`, `needsAccounts`, `needsFirstImport`, `needsReview`
- setup progress summary returned by `/api/app/state`
- an API to add or update import accounts after initial bootstrap
- a UI-safe derived account label separate from raw ledger account paths
- optional support for creating manual accounts without a predefined institution template

The existing APIs already support key parts of the new flow:

- workspace bootstrap
- workspace select
- import candidate detection
- upload, preview, and apply

That means setup revamp can be phased without replacing the import engine.

## Implementation Plan

### Phase 1: Flow and Framing

- convert setup into a staged checklist layout
- collapse workspace path and ledger account fields into advanced affordances
- improve state-driven copy and success messaging
- keep first import embedded in setup via existing APIs where possible

Target outcome:
- first-run feels guided instead of form-heavy

Status:
- implemented

### Phase 2: Account Setup Improvements

- add post-bootstrap account management
- auto-generate destination accounts by default
- support manual/unsupported institutions cleanly
- add per-account readiness statuses

Target outcome:
- users can add accounts without learning accounting structure

Status:
- partially implemented
- add/edit and auto-generated destination accounts are done
- manual institution support and fuller per-account status work remain

### Phase 3: Stronger Handoff

- show a completion summary after first import
- route users directly to unresolved category work when needed
- enrich overview state so setup completion feels consequential

Target outcome:
- setup blends naturally into everyday product use

Status:
- partially implemented
- setup now routes users toward review or overview after import
- richer completion summaries and stronger post-import polish still remain

## Risks

- Hiding too much technical detail could frustrate power users if advanced controls become hard to find
- Embedding first import inside setup can create a larger page if structure is not disciplined
- Supporting manual institutions without care could weaken parser/template clarity

## Non-Goals

This revamp does not require:

- bank aggregation or direct bank linking
- budgeting features
- forecasting or goals
- changes to import safety semantics
- replacing the plain-text workspace model

## Definition of Done

The setup revamp is successful when:

- a new user can create a workspace and complete a first import without needing accounting terminology
- the default path feels like one continuous flow instead of screen-hopping
- advanced configuration is available, but no longer dominates first-run
- the app lands the user in a useful post-setup state with clear next actions
