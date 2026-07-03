# Context-independent global keymap

The Phase 2 makeover commits the app to a keyboard-first power-user model in the
Linear / Gmail / vim lineage: `g`-prefix navigation (`g t` → Transactions),
`j`/`k` row movement, single-key actions, a `?` cheat-sheet, and the existing
Ctrl+K command palette. But unlike those apps — where a single key rebinds to
whatever "edit"/"create" means on the currently focused surface — we require that
**one key means one verb app-wide**. A key's *availability* is contextual (active
when its target exists, inert otherwise) but its *meaning* never changes. So `c`
cannot be "create" on one page and "categorize" on another.

Two refinements make this practical:

- **Constant-verb / contextual-target keys are allowed.** `j`/`k` ("move down/up
  in the active list"), `Enter` ("activate the focused item"), and `Esc`
  ("close/back out") keep a single consistent meaning even though *which* list or
  item they act on depends on focus. Power users expect these and we do not flout
  that expectation.
- **Case is part of the budget.** `c` and `C` are distinct keys and may hold
  different verbs (e.g. `C` create vs `c` categorize), so the ~26-letter space is
  not a real constraint once `g`-prefix removes navigation from the action budget.

Modifiers (Ctrl/Alt) are reserved for the few truly-global actions that must fire
even from inside a text input (Ctrl+K palette). Depth: every primary action is
key-reachable everywhere; full roving-focus list navigation is implemented on the
three data registers (Transactions, Review, Reconcile). Discoverability rides on
three layers — inline hints next to actions, the `?` cheat-sheet overlay, and the
Ctrl+K palette as the searchable command index. The keymap is a single global
table implemented by extending the existing command registry
(`command-registry.ts`), not per-page keydown handlers.

## Considered Options

- **Linear-style contextual single keys** (a key does whatever the focused
  surface defines) — rejected; the user explicitly does not want a key's verb to
  change by context, because it is a "surprise" that undercuts the no-surprises
  goal.
- **Bespoke finance-tuned scheme** — rejected; the Linear/Gmail/vim vocabulary is
  free to adopt and spares the target audience any relearning.
- **Modifier-only shortcuts** (every action needs Ctrl/Alt) — rejected; too few
  ergonomic combos, fights text inputs, and abandons the fast single-key feel that
  defines the power-user model.

## Consequences

The keymap must be designed as one globally-budgeted table, not assembled
per-page. Every list surface needs a focused-item concept with roving `tabindex`
and a visible active indicator. A key with no target in the current context is
shown inert/greyed in the cheat-sheet — never repurposed. Future contributors add
verbs to the global table and must check for collisions there; they must not
invent page-local single-key bindings. If the global verb budget ever feels
tight, reach for `Shift` (case) or a new prefix before breaking the
one-key-one-verb rule.
