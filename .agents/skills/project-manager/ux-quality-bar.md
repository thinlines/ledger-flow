# UX Quality Bar

Use this reference when evaluating whether a task is ready to close, or when defining what "done" means for a feature.

## Five-Star Standard

The product should feel:

- clear on first use
- fast enough to maintain trust
- visually coherent
- forgiving when the user makes mistakes
- consistent across primary flows

## Finance-Specific Trust Bar

For a personal finance product, correctness is the primary quality dimension. A misleading state erodes more trust than a missing feature.

- Balances, totals, and pending counts must reflect reality exactly
- Misleading states (e.g., settled transfers labeled as pending) are high-severity defects — fix before closing
- The product must fail closed: if it cannot confidently determine state, show the conservative result, not a guess
- Never hide or suppress activity the product cannot explain
- Pending sections and pending counts must represent genuinely unresolved work only
- Original imported data (amounts, dates, descriptions) must remain visible and unchanged
- Internal accounting terms must not appear in default copy (no postings, journals, ledger accounts, transfer-clearing accounts)

## Core UX Gates

Before closing a task, verify:

- The primary user can complete the main job without guidance.
- The UI hierarchy makes the next action obvious.
- Labels, buttons, and empty states use plain language.
- Error states explain what happened and how to recover.
- Loading, success, and failure feedback are visible.
- Defaults are sensible and reduce user effort.
- No internal accounting or system terms appear in default-path copy.
- The product feels internally consistent in spacing, copy tone, and interaction patterns.

## Common Ways to Miss the Bar

- Shipping functionality with incorrect or misleading summary numbers
- Leaving states that contradict each other (UI says pending, ledger is settled)
- Handling the happy path only; leaving error and empty states vague
- Introducing new internal states without corresponding UI explanation
- Treating visual consistency or copy correctness as optional polish

## Quality Review Prompts

Before closing a task, ask:

- Where will a user be confused or misled by the current state?
- What number or status could be wrong, and what does that cost in trust?
- Which edge state will most damage trust if handled poorly?
- What should be simplified before anything new is added?
- Does this feel intentionally designed, or merely assembled?

## Release Recommendation

If the outcome is functional but presents misleading state, incorrect numbers, or breaks the pending/posted/settled contract: reduce scope or fix the trust issue before closing. Functional but misleading is worse than not shipped.
