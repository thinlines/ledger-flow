# Ledger Flow

A GUI-first bookkeeping app for people who want a polished personal finance workspace without learning plaintext accounting. Data lives in open, human-readable [Ledger](https://www.ledger-cli.org/) files for durability and portability, but the product feels like a finance app first.

> **Status:** Work in progress, mostly AI-generated. Built as an experiment in collaborating with coding agents on a real consumer-grade app. Expect rough edges, breaking changes, and incomplete features. Not yet recommended for managing your actual finances.

## What it's for

Ledger Flow tries to answer three questions every time you open it:

- Where do I stand right now?
- What changed recently?
- What needs attention next?

It leads with money, accounts, balances, and activity — not journals and postings. The plain-text foundation stays real and durable, but behind the curtain in normal workflows.

## Requirements

- [Ledger](https://www.ledger-cli.org/) CLI (the canonical accounting engine — Ledger Flow reads and writes its journal files)
- [Python 3.11+](https://www.python.org/) and [uv](https://docs.astral.sh/uv/) for the backend
- [Node.js 20+](https://nodejs.org/) and [pnpm](https://pnpm.io/) for the frontend
- [just](https://github.com/casey/just) (optional, for the dev shortcuts below)

## Install

```sh
git clone https://github.com/thinlines/ledger-flow.git
cd ledger-flow

# Backend (FastAPI + uvicorn, managed by uv)
cd app/backend && uv sync && cd ../..

# Frontend (SvelteKit + Vite + Tailwind v4)
cd app/frontend && pnpm install && cd ../..
```

## Run

In two terminals:

```sh
just app-backend     # http://127.0.0.1:8000
just app-frontend    # http://127.0.0.1:5173
```

Without `just`:

```sh
cd app/backend  && uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
cd app/frontend && pnpm dev
```

Then open the frontend URL in your browser.

## Project docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — system shape, boundaries, invariants
- [ROADMAP.md](ROADMAP.md) — product direction and milestones
- [DECISIONS.md](DECISIONS.md) — durable tradeoffs and rationale
