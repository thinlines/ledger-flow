# Ledger Flow

Ledger Flow is a local-first personal finance app built on top of plain-text [Ledger](https://www.ledger-cli.org/) journals. It gives you a polished workspace for setting up accounts, importing statements, reviewing uncategorized activity, and tracking balances without turning everyday use into an accounting exercise.

Everything stays on your machine in human-readable files, so your books remain durable and portable.

## Capabilities

- Guided setup for creating a new workspace or opening an existing one
- Account management for assets and liabilities, including opening balances
- CSV statement import with preview, duplicate detection, and file archiving
- Review queue for uncategorized transactions and transfer matching
- Rules for automating recurring categorization decisions
- Dashboard, account, and transaction views for balances, cash flow, and recent activity

## Installation

### Requirements

- [Ledger CLI](https://www.ledger-cli.org/)
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- [pnpm](https://pnpm.io/)
- [`just`](https://github.com/casey/just) (optional, for the shortcut commands below)

### Clone and install dependencies

```sh
git clone https://github.com/thinlines/ledger-flow.git
cd ledger-flow

cd app/backend
uv sync
cd ../frontend
pnpm install
cd ../..
```

### Run the app

Using `just`:

```sh
just app-backend
just app-frontend
```

Without `just`:

```sh
cd app/backend
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```sh
cd app/frontend
pnpm dev
```

Open `http://127.0.0.1:5173` in your browser, then follow the setup flow to create or select a workspace and import your first account.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [ROADMAP.md](ROADMAP.md)
- [DECISIONS.md](DECISIONS.md)
