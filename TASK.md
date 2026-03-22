# Current Task

## Objective

Unblock financed liability opening balances in Accounts so a user can create a liability such as a car loan and have its starting balance offset the correct existing tracked account instead of always posting to opening-balances equity.

## Deliverables

- Add a plain-language selector near opening balance in Accounts create and edit flows so the user can choose where the starting balance comes from.
- Default that selector to opening-balances equity, but allow the user to pick an existing tracked account when the starting liability should offset something already tracked.
- Limit this cut to accounting correctness for the opening entry:
  - do not introduce a durable paired-account or relationship model
  - do not frame the selector as a long-term account link
- Write the opening-balance transaction against the selected offset account instead of `Equity:Opening-Balances` when a tracked account is chosen.
- Make edit flows derive the selected offset from the existing opening-balance transaction itself instead of storing new relationship state on the tracked account.
- Keep copy finance-first and concrete so a user understands what account the starting balance will reduce or increase.
- Keep roadmap, decisions, and agent rules aligned with this narrower cut line while the work lands.

## Success Criteria

- A user can create or edit a liability tracked account such as a car loan and choose an existing tracked account as the starting-balance offset.
- The resulting opening-balance journal entry posts against the selected account instead of `Equity:Opening-Balances`.
- The default path still works for ordinary opening balances that should continue to offset equity.
- The product does not add a new persistent account-pairing model just to support this starting-balance fix.

## Out of Scope

- Durable account-link or paired-account state on tracked accounts
- Guided vehicle-plus-loan or property-plus-mortgage creation flows
- Full amortization schedules or payoff planning
- Automated valuation or depreciation for vehicles or real estate
- Broad reporting, budgeting, or forecasting expansion

## Replacement Rule

Replace this file when the next active engineering task begins.
