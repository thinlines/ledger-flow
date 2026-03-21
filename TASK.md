# Current Task

## Objective

Unblock balance-sheet account setup in Accounts so a user can create liability accounts such as car loans and place opening balances correctly without editing advanced account names or relying on inferred UI labels.

## Deliverables

- Make asset vs liability an explicit primary choice in Accounts setup and edit flows.
- Make subtype behavior trustworthy across account creation and account inventory:
  - explicit subtype selection should be saved as product state
  - inferred subtype presentation should either be persisted deliberately or clearly labeled as suggested, not shown as authoritative state
- Rewrite manual-account copy, placeholders, and summaries so the main path talks about what the user owns or owes, not ledger internals.
- Improve `/accounts/configure` hierarchy on desktop and mobile so the active create/edit flow is dominant.
- Keep Rules and Review focused on P&L categorization; Accounts remains the home for tracked balance-sheet accounts.
- Define the immediate follow-on for a paired financed asset + loan flow once liability account setup is unblocked.
- Keep roadmap, decisions, and agent rules aligned with this cut line while the work lands.

## Success Criteria

- A user can create a manual liability tracked account such as a car loan from Accounts without editing the advanced account name.
- A user can enter an opening balance for that liability confidently and understand how it will affect balances.
- The product no longer presents inferred account subtypes as if they were saved state.
- The next bottleneck after this task is the paired financed-asset workflow itself, not confusion about how to create the liability account.

## Out of Scope

- Full amortization schedules or payoff planning
- Automated valuation or depreciation for vehicles or real estate
- Broad reporting, budgeting, or forecasting expansion
- General transfer automation beyond the bounded financed-asset follow-on

## Replacement Rule

Replace this file when the next active engineering task begins.
