# Product Roadmap

This document captures the near-term product direction for Ledger Flow.
It is a planning document, not a strict delivery contract.

> Context ownership: `README.md` covers product purpose, `ARCHITECTURE.md` covers the current system, `AGENT_RULES.md` covers implementation rules, `TASK.md` covers the active task, and `DECISIONS.md` covers durable rationale. `ROADMAP.md` remains the source of truth for direction and milestones.

## Current Focus

Feature 9b (manual transaction merge) is active. Feature 10 (interactive dashboard) is queued after 9b.

## Shipped Features

1. **Manual transaction entry + import matching** — `:manual:` tag, unknowns review match mode, quality ranking, metadata carryover. (`a4280b7`)
2. **Transaction clearing status** — parse, display, and toggle clearing status on register rows. (`7ba39c9`)
3. **Dashboard facelift + polish** — layout redesign, momentum line, day-grouped activity, per-account staleness, cash flow presets. (`cebb175`, `07b2ba5`)
4. **Event-sourced undo** — six undoable event types (delete, recategorize, unmatch, manual-entry-create, notes-update, status-toggle), 8s undo toast, recent activity sheet with per-row undo. (`2796461`)
5. **Dashboard drill-down + activity view** — clickable category trends and cash flow rows, cross-account activity view, URL-param filter state. (`0d707f1`)
6. **Dashboard insight loop + financial direction** — direction panel (runway gauge, net worth sparkline, recurring vs discretionary split, notable signals, loose-ends), transactions screen rethink (unified filter-driven page, running balance, N-1 posting rule, detail sheet, search formula syntax), shell and copy polish (mobile nav, sign conventions). (`692581d`, `7cf94a5`)
7. **Statement reconciliation (8a–8f)** — Quicken/YNAB-style explicit reconciliation expressed as journal balance assertions. Core track shipped: backend endpoint, reconciliation route, duplicate review with merge substrate, subset-sum diagnostic, assertion rendering across surfaces. Follow-ups (8g–8j: history, statement PDF, adjustment posting, edit confirmation) are deferred — the current workaround of manual journal edits is adequate until a concrete need surfaces. (`7cb401d`..`e731e21`). See `plans/statement-reconciliation.md`.
8. **Match-suggestion ranking fix (9a)** — replaced 4-tier system with continuous scoring (amount tolerance, payee similarity, date decay). (`5f41acd`)
9. **CSV parser refactor + bank adapters** — Chase, Ally, U.S. Bank, Bank of America, Citibank.
10. **Transfer flows** — auto-reconcile bilateral pairs, manual resolution, grouped-settlement trust fix.

## Active: 9b — Manual Transaction Merge

Generic merge workflow on the transactions page. Multi-select + Merge action to combine two transactions in the journal, preserving both `source_identity` and `source_payload_hash` values on the survivor so future imports of either payee variant are recognized as duplicates. Backend generalizes the reconciliation merge substrate from 8d; emits a structured event for undo. See `plans/transaction-merge.md`.

## Queued: Feature 10 — Interactive Dashboard

Power BI-style dashboard with Apache ECharts charts, cross-filter state, time-hierarchy drill-down (month → week → day), and a global date range picker. Replaces CSS-bar charts with interactive visuals. Four sub-features:

- **10a. Backend history payload + mtime cache** — expose `categoryHistory[]` and `cashFlowHistory[]`; mtime-based transaction cache; lazy-fetch endpoint.
- **10b. ECharts cash flow chart + drill state** — grouped bar chart replacing CSS bars; `DrillState` and breadcrumb.
- **10c. Category sparklines + detail panel** — per-row 6-month mini sparklines; spending-drivers donut; selected-category time series + lazy transaction list.
- **10d. Global date range picker** — bits-ui `DateRangePicker`; preset buttons; reactive `$derived` data filters.

See `plans/interactive-dashboard.md`.

## Constraints

- Preserve the existing `new` / `duplicate` / `conflict` import model.
- Keep `workspace/` canonical and `.workflow/` disposable.
- Keep transfer-resolution logic, import-identity generation, and journal writes in backend services.
- Hide transfer-clearing and journal-file details from default UI copy.
- Fail closed when the system cannot safely protect against future duplicate imports.
- The `:manual:` tag is standard ledger metadata — no custom extensions to the format.

## Deferred

These are valid ideas, but they are not current priorities:

- Transaction editing
- Statement reconciliation follow-ups (8g–8j: reconciliation history, statement PDF linking, adjustment-transaction button, pre-reconciliation edit confirmation)
- Configuration UI (date format, currency settings, etc.)
- Merchant management UI
- Expanding the rule language beyond the current limited matching model
- Debt-payment decomposition and richer liability servicing workflows
- Multi-currency account support
