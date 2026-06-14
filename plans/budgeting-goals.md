# Budgeting & Goal Tracking — Design Analysis

Early-stage design sketch for adding budgeting and financial goal tracking to Ledger Flow. Not yet on the delivery sequence — this captures the research, architecture options, and UI direction for when the feature moves to active.

## Ledger Primitives

Full research in `docs/ledger-budgeting-goals-features.md`. The key insight: ledger's native syntax covers the runtime behavior (budget enforcement, goal funding, forecasting) without any custom extensions. The app builds a UI lens on top.

| Concept | Journal primitive | CLI query |
|---------|-------------------|-----------|
| Spending budget | `~ Monthly` periodic transaction | `--budget --monthly balance ^expenses` |
| Budget vs. actual | (same) | `--budget`, `--add-budget`, `--unbudgeted` |
| Goal funding rule | `= "goal:X" :: /^Income/` automated transaction | `bal Goals:X` |
| Balance cap | `account("Goals:X").total < $5000` in predicate | (fires until cap) |
| Pause/resume | `= goal:X disable` / `= goal:X enable` | (rule inactive) |
| Batch control | `= "goal:.*" disable` | (pattern match) |
| Forecast | periodic transactions + `--forecast "d<[6 months hence]"` | projected balances |
| Envelope tracking | `[Budget:$account]` virtual postings | `bal ^Budget` |

## Architecture Decision: Hybrid (Journal + Config)

**Journal** holds what `ledger` understands: periodic transactions, automated transactions, virtual postings, metadata tags.

**`workspace/settings/budgets.toml`** (or similar) holds what only the app needs: goal display names, target amounts, deadlines, priorities, funding rule references. This mirrors how tracked accounts work today — journal has transactions, `workspace.toml` has display names and wiring.

Pure-journal (approach A) was considered but rejected: ledger has no native concept of "this goal's target is $5,000 by December." That's display metadata the app must store somewhere.

## Open Questions

1. **Virtual vs. real accounts for goals?** Virtual postings (`[Goals:Emergency]`) keep the real balance sheet clean but add complexity. Real sub-accounts (`Assets:Goals:Emergency`) are simpler but pollute `ledger bal`. User preference needed.

2. **Budget scope: spending budgets only, or income allocation too?** "Spend at most $500/mo on dining" (periodic transaction) vs. "allocate 10% of every paycheck to savings" (automated transaction) are different workflows.

3. **Nav placement**: New "Planning" section between Daily Use and Automation, or fold into existing routes? The dashboard shows summary; the management surface needs a home.

4. **Interaction with direction panel**: Runway and net worth are currently derived-only (DECISIONS.md §13). Goals/budgets would be the first user-defined targets feeding into "Where should I go next?"

## Suggested Phases

### Phase 1: Spending budgets (periodic transactions)
- CRUD for `~ Monthly` / `~ Weekly` blocks via UI
- `ledger --budget --monthly balance` on the backend
- Budget overview on dashboard (actual vs. budget per category)
- Budget management on a `/plan` route
- No goals, no automated transactions, no forecasting

### Phase 2: Savings goals (automated transactions + config)
- Goal definitions in config file
- Named automated transactions generated from goal config
- Balance-capped funding rules (`account().total < $TARGET`)
- Goal progress visualization (balance vs. target)
- Goal status feeds into dashboard direction panel

### Phase 3: Forecasting + projections
- `--forecast` integration for "when will I reach my goal?"
- Projected completion dates on goal cards
- What-if scenarios (change funding amount, see new timeline)

### Phase 4: Envelope budgeting (if demand)
- Virtual posting layer for envelope tracking
- Per-envelope balances and carry-forward

## User Stories

### Phase 1
1. Set a monthly spending budget for any expense category
2. See actual vs. budget this month at a glance on the dashboard
3. See which categories are over/under budget and by how much
4. Create, edit, delete budget categories on a dedicated page
5. Budgets are standard `~ Monthly` periodic transactions — `ledger --budget` works from the CLI

### Phase 2
6. Create a savings goal with name, target amount, optional deadline
7. Assign a funding rule (e.g., "$200/paycheck from Checking")
8. See progress toward each goal (balance, % complete, remaining)
9. Funding rules stop automatically when target is reached
10. Pause/resume funding during tight months

## UI Direction

### Dashboard integration
Budget tile joins the direction panel alongside runway and net worth trend:
- Overall spend rate as progress bar + days remaining
- One-line notable when a category is near/over budget
- One-line goal showing nearest milestone
- Click drills to `/plan`

### `/plan` route — two sections

**Budget tab**: Month navigation, overall progress bar, per-category rows with progress bars (the primary visual, not numbers), warning state when pace exceeds budget, unbudgeted line at bottom, "Edit budget" action. Each row clicks through to filtered `/transactions`.

**Goals tab**: Card per goal (not a table — each goal is its own story). Progress bar + projected date as hero metrics. Funding rule in plain language ("$200/paycheck from Checking"). Active/Paused/Complete status. Pause/Resume/Edit actions.

### Creation flows

**Budget category**: Sheet with category picker, amount, period (monthly/weekly/yearly).

**Savings goal**: Two-step sheet. Step 1: name, target, optional deadline. Step 2: funding amount, frequency (paycheck/month/week), source account, cap behavior. Live "at this rate" projection updates as user adjusts amount.

### Data flow

```
User action          -> Journal write              -> Ledger query           -> UI
Create budget        -> ~ Monthly block            -> --budget --monthly bal -> Budget overview
Create goal          -> = "goal:X" :: ... block    -> bal Goals:X            -> Goal progress
                       + budgets.toml entry
Pause goal           -> = goal:X disable           -> (rule inactive)       -> "Paused" status
Fund goal (paycheck) -> (auto-transaction fires)   -> bal Goals:X           -> Updated progress
Goal reached         -> (rule stops at cap)        -> bal Goals:X = target  -> "Complete" status
Forecast             -> --forecast "d<[6mo]"       -> projected balances    -> "Sep 2026" date
```

Every state is derivable from the journal + one config file. The app is a lens, not a database.
