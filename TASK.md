# Current Task

## Objective

Reduce friction in Accounts setup by choosing sensible defaults automatically. A user adding or editing an account should not have to resolve obvious starting-date or subtype choices manually when the product can infer them confidently.

## Deliverables

- Default the opening date in Accounts configuration to January 1 of the current calendar year for fresh account drafts.
- Preserve any saved opening date on edit. If an existing account has an opening balance but no saved date, present the same sensible default instead of leaving the field blank.
- Remove copy that asks the user to add a starting date manually when the product can now supply that default for the common case.
- Review Accounts inventory and balance-trust messaging so warnings are reserved for accounts that truly lack any starting balance or imported history, not merely a defaultable date detail.
- Auto-sync the subtype dropdown in Accounts configuration with the existing name heuristic as the user types.
- Only auto-apply the heuristic while subtype is still broad or still matches the last automatic suggestion. If the user deliberately picks a different subtype, preserve that choice.
- Keep asset vs liability selection explicit for this cut. Do not silently flip the balance-sheet kind just because the name heuristic points at a subtype in the other group.
- Keep behavior aligned across manual, supported-institution, and custom CSV account setup modes.

## Success Criteria

- On March 22, 2026, a fresh account draft would prefill the opening date as January 1, 2026. The implementation should keep that behavior dynamic for future years.
- A user can save a starting balance without first choosing an opening date manually unless they want a different date.
- Accounts surfaces no longer nudge users to add a starting date when the default already covers the common case.
- Typing a liability account name that matches the current heuristic, such as a credit card name, updates the subtype dropdown to the matching subtype automatically.
- A manual subtype override is not repeatedly overwritten by later keystrokes.
- This work lands without introducing a broader onboarding redesign or a new persistent relationship model.

## Out of Scope

- New subtype heuristics beyond the current keyword-based matcher
- Automatic switching of asset vs liability kind
- Broad redesign of the Accounts dashboard or onboarding flow outside this defaults pass
- Data-model changes that exist only to support UI defaults
- Bulk backfill or migration of existing accounts beyond normal edit behavior

## Replacement Rule

Replace this file when the next active engineering task begins.
