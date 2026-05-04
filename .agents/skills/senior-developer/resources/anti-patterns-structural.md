# Structural Anti-Patterns

- Do not add a boolean parameter to toggle behavior inside a function. Extract the variant into its own function or let the caller choose the right code path.
- Do not duplicate validation or computation that already exists upstream. Find the existing function and call it; if it needs a small change, change it rather than forking a copy.
- Do not catch and silence exceptions in business logic. If an error can happen, handle it with a meaningful recovery or let it propagate. A bare `except: pass` or `catch {}` hides the bug that will surface later in a harder-to-diagnose form.
- Do not store derived state that can be recomputed from the source of truth. In this project the ledger journal is canonical — a user running `ledger -f 2026.journal` must be able to reproduce every number the app shows. Caching is fine; persisting a second copy of truth is not.
