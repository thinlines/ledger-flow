# Monarch Money — Detail Sidebar Feature Analysis

Analyzed from a screenshot of Monarch's transaction detail sidebar (April 2026). Each feature is mapped to our current roadmap status.

## Features Observed

### 1. Review Status Badge

**What Monarch shows:** A green "Reviewed" pill with checkmark at the top of the sheet, plus a visibility (eye) icon. Clicking toggles the transaction between reviewed and unreviewed states.

**Our status:** Not planned. Our clearing-status circle (unmarked / pending / cleared) serves a similar but distinct purpose — it tracks bank reconciliation, not user review. A "reviewed" toggle could layer on top if we add a review-queue workflow beyond the current unknowns flow. Low priority unless we find users want to mark known-category transactions as "seen."

### 2. Merchant Logo / Branding

**What Monarch shows:** A large square merchant icon (Walmart logo) displayed prominently above the payee name.

**Our status:** Not planned. Would require a merchant-logo service (Plaid enrichment, Brandfetch, or similar). Nice visual polish but not load-bearing for any workflow. Could revisit when merchant management lands.

### 3. Amount + Account Chip

**What Monarch shows:** Amount in large text top-right. Account label ("Joint Credit Card") with a small icon below it.

**Our status:** Shipped in Phase 3. The detail sheet header shows payee, amount, and account label. We don't have per-account icons but the account name is visible.

### 4. Merchant Transaction History Link

**What Monarch shows:** "View 29 transactions" link below the payee, scoping to all transactions from the same merchant.

**Our status:** Deferred. Referenced in `transactions-rethink.md` as: "The 'View N transactions from this merchant' link in the detail sheet is deferred until merchant management exists." This is a Phase 5+ feature that depends on merchant identity being a first-class concept. Currently the payee string is the only merchant identifier.

### 5. Editable Date Field

**What Monarch shows:** A full date input with calendar picker. Shows "Original Date: August 4, 2025" below when the user has changed the date, preserving the import date.

**Our status:** Deferred to Feature 9 (transaction editing). The plan explicitly says: "It does not introduce transaction editing (date, payee, amount). That's the deferred Feature 9 — this plan creates the surface for it but does not implement it." Our sheet currently shows date as read-only. The "original date" preservation pattern is a good design detail to remember when we implement editing.

### 6. Category Combobox + Split Link

**What Monarch shows:** A dropdown showing the current category with an icon prefix (paw for "Pets"). A "Split" link to the right of the "Category" label opens the split-transaction dialog.

**Our status:** Partially planned.
- **Category combobox:** Planned for the detail sheet (same combobox as the row). Deferred in Phase 3 because the recategorize endpoint only resets to `Expenses:Unknown` — doesn't support setting a specific new category. Needs a backend `newCategory` parameter.
- **Split link:** Planned as a disabled placeholder in v1. Full split editing is deferred but ledger supports splits natively. See `monarch_money_transaction_split.png` reference in the plan.
- **Category icon:** Not planned. Would need a category-to-icon mapping. Nice visual touch but not essential.

### 7. Goal Selector

**What Monarch shows:** A dropdown to assign the transaction to a financial goal. "Select goal..." placeholder.

**Our status:** Not planned. Goals (savings targets, debt payoff, etc.) are not part of the current product scope. This is a distinct feature that would need its own data model. Could be relevant if we add budgeting or savings-goal features.

### 8. Notes Textarea

**What Monarch shows:** Free-text notes field. "Add notes to this transaction..." placeholder.

**Our status:** Planned as deferred placeholder. The plan says: "Notes — textarea (deferred; placeholder for now)." Implementation would store notes as ledger comment metadata (`;` lines or `; note:` tags) on the transaction block. Straightforward to build when prioritized.

### 9. Tags Input

**What Monarch shows:** Searchable tag input. "Search tags..." placeholder with dropdown chevron.

**Our status:** Planned as deferred placeholder. The plan says: "Tags — chip input (deferred; placeholder for now)." Ledger has native tag support (`:tag:` syntax), so the backend foundation exists. Needs UI for tag management and the detail sheet input.

### 10. Attachments

**What Monarch shows:** "Add an attachment" with paperclip icon. Supports receipt photos and documents.

**Our status:** Planned as deferred placeholder. The plan says: "Attachments — drop zone (deferred; placeholder for now)." This would need file storage (local or cloud), a file-upload endpoint, and metadata linking attachments to transactions. More infrastructure than the other deferred fields.

### 11. Three-Dot Overflow Menu

**What Monarch shows:** Three-dot icon in the top-right header for less-frequent actions.

**Our status:** Shipped in Phase 3. Our sheet has a three-dot popover menu with Delete, Reset Category, and Undo Match actions.

### 12. Close Button

**What Monarch shows:** X icon in the top-right corner.

**Our status:** Shipped in Phase 3.

## Priority Takeaways

| Feature | Effort | Value | Recommendation |
|---------|--------|-------|----------------|
| Category combobox (set specific) | Medium (backend + frontend) | High | Next after Phase 4 — needs `newCategory` param on recategorize endpoint |
| Notes | Low (ledger comments) | Medium | Good first metadata field to ship |
| Tags | Medium (ledger tags + UI) | Medium | Ship after notes |
| Editable date | Medium (Feature 9) | Medium | Part of broader transaction editing |
| Merchant history link | Low (UI) / Medium (merchant identity) | Medium | Blocked on merchant management |
| Attachments | High (file storage infra) | Low-Medium | Defer until infrastructure need is clearer |
| Goal selector | High (new feature domain) | Low | Out of scope until budgeting features exist |
| Review status | Low | Low | Only if review-queue workflow expands beyond unknowns |
| Merchant logo | Low-Medium (external API) | Low | Visual polish, not workflow |
| Category icon | Low | Low | Visual polish |
