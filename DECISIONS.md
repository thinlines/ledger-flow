# Decisions

This document records stable product and architecture choices that explain why the repo works the way it does today.

## 1. Optimize for a GUI-First Finance Product

**Decision:** The primary experience is a polished personal finance app, not a thin UI over plaintext accounting tools.

**Why:** Most users should be able to manage their finances without learning developer tooling or accounting internals.

**Implication:** Primary UI copy talks about money, accounts, spending, activity, and next steps. Technical accounting language belongs in advanced surfaces or documentation.

## 2. Keep Plain Text as the Foundation, Not the Default Mental Model

**Decision:** Canonical financial data lives in open, human-readable files, but the default product path hides that storage model.

**Why:** Durability and portability matter, but they should not dominate the user experience.

**Implication:** Paths, journals, postings, and ledger-account mappings stay behind explicit reveals, advanced workflows, or docs.

## 3. Make Workspace Files Canonical and Operational State Disposable

**Decision:** `workspace/` is the source of truth. `.workflow/` exists for speed, resumability, and import memory only.

**Why:** Accounting truth should remain portable, inspectable, and recoverable outside the app.

**Implication:** If `.workflow/` is lost or stale, rebuild it from the workspace. Never let it override journals or workspace config.

## 4. Keep Imports Idempotent, Conflict-Visible, and Non-Rewriting

**Decision:** Importing adds only new transactions, skips duplicates, and surfaces conflicts instead of rewriting history.

**Why:** This preserves rich journals:

- Manual comments, tags, and edits remain untouched.
- Rerunning an import stays safe when identity fields are stable.
- Journal text remains authoritative, while the import index acts as audit and idempotency memory.

**Implication:** Preserve source identity and payload metadata, require preview before apply, and never auto-modify transactions that already exist in journals. New transactions may be merged into journal date order, but existing transaction text remains unchanged.

## 5. Treat Eventual Consistency as a Product Principle

**Decision:** Users can build financial history and account coverage incrementally over time.

**Why:** Real users often begin with incomplete imports, unsupported institutions, opening balances, or partial historical backfill.

**Implication:** Adding accounts later, seeding opening balances, and backfilling older years should not break the current picture.

## 6. Make the Dashboard the Daily Home

**Decision:** The default landing experience should emphasize financial state, recent change, and next actions instead of system status.

**Why:** Once setup and import work, the product should still be useful when there is little maintenance work to do.

**Implication:** Import, review, and rules support the dashboard and accounts experience instead of defining the product identity.

## 7. Use Setup for Momentum, Not Permanent Administration

**Decision:** Setup exists to get a user from zero to first useful result quickly, then hand off to normal product surfaces.

**Why:** First-run should feel guided and lightweight instead of becoming the permanent home for account management or diagnostics.

**Implication:** Account management, import work, and review must all remain available outside setup, and advanced bootstrap detail should stay hidden by default.
