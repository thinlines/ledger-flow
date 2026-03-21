# Ledger Flow

Ledger Flow is a GUI-first bookkeeping app for people who want a polished personal finance workspace without learning plaintext accounting. It stores financial data in open, human-readable files for durability and portability, but the product should feel like a finance app first.

## Product Purpose

Ledger Flow helps users answer three questions every time they open the app:

- Where do I stand right now?
- What changed recently?
- What needs attention next?

The product should make setup, importing, review, account management, and daily visibility feel like one continuous finance workflow rather than a collection of accounting tools.

## Audience

- People managing personal finances who may be nontechnical and not accounting specialists.
- Contributors building a consumer-grade finance workspace, not a tooling-first plaintext ledger interface.

## Product Posture

- Use money, accounts, balances, spending, activity, and next steps as the main product language.
- Treat the GUI as the default way to manage data; CLI tooling is optional developer infrastructure.
- Keep the plain-text foundation real and durable, but behind the curtain in normal workflows.
- Make common tasks obvious, safe, and fast; move advanced details into explicit reveals or secondary screens.
- Support zero-file bootstrapping, idempotent import, and incremental backfill over time.
- Keep accounting truth in workspace files and use operational state only to speed up UX and remember workflow state.

## Experience North Star

Ledger Flow should feel like a polished, consumer-grade personal finance application, not a frontend for plaintext accounting. The default interface should lead with financial outcomes and guidance, keep one dominant next action per screen, and hide implementation details such as paths, journals, and ledger-account mappings unless the user explicitly needs them.

## Context Map

- [README.md](README.md): product purpose and posture
- [ARCHITECTURE.md](ARCHITECTURE.md): current system shape, boundaries, and invariants
- [AGENT_RULES.md](AGENT_RULES.md): implementation, copy, and change-safety rules
- [TASK.md](TASK.md): the active task only
- [DECISIONS.md](DECISIONS.md): durable tradeoffs and rationale
- [ROADMAP.md](ROADMAP.md): product direction and milestones
