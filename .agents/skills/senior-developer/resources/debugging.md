# Debugging and Investigation

When the root cause is unclear, follow this sequence rather than guessing:

1. **Reproduce first.** Create or identify the minimal input (journal fixture, CSV, API request) that triggers the wrong behavior. If you cannot reproduce it, you do not understand it yet.
2. **Trace the actual execution path.** Follow the data from source (journal file or CSV) through the service layer, API response, and into the UI. Read the code that runs, not the code you think runs. Print intermediate values or use a debugger when reading alone is ambiguous.
3. **Identify the broken invariant.** Every bug is a violated assumption. Name the assumption: "this function expected one candidate but received two", "this date comparison used `<` instead of `<=`", "this account ID was `None` because the config was stale." Fix the invariant, not just the symptom.
4. **Check for the same class of bug nearby.** If the broken invariant could be violated in a sibling function or parallel code path, check those too. Fix them in the same change if the scope is small; file a follow-up if it is not.
5. **Verify the fix does not mask a deeper issue.** If you are adding a guard clause, ask whether the upstream code should have prevented the bad state in the first place. A guard is acceptable when the upstream fix is out of scope, but name the debt.
6. **Compare against the canonical source.** For any data-correctness issue, run the equivalent `ledger` CLI query against the journal file. If the app and `ledger` disagree, the app is wrong.
