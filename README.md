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
# Or start both
just start-servers
```

For the packaged single-server app, build the frontend into the backend package
and install the CLI:

```sh
cd app/frontend
pnpm build
cd ../backend
uv tool install --editable .
ledger-flow server --workspace /path/to/ledger-flow-workspace --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` in your browser. The same process serves the UI
and the `/api` routes.

For development without a packaged frontend, run the API and Vite dev server
separately:

```sh
cd app/backend
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```sh
cd app/frontend
pnpm dev
```

Open `http://127.0.0.1:5173` in your browser for the dev UI.

### Create a manual transaction from the CLI

With the API server running, `ledger-flow transactions create` creates a normal
two-posting manual transaction. Use `--account` for the source tracked Ledger
account and `--to` for the destination posting account:

```sh
ledger-flow transactions create \
  --account "Assets:Bank:Checking" \
  --to "Expenses:Eating Out" \
  --payee "Burger King" \
  --amount "20.00" \
  --date "2026-07-02"
```

`--to` is destination posting vocabulary, not category-only vocabulary. It can
point at any declared Ledger account, including another asset or liability
account:

```sh
ledger-flow transactions create \
  --account "Assets:Bank:Checking" \
  --to "Assets:Bank:Savings" \
  --payee "Move to savings" \
  --amount "200.00" \
  --date "2026-07-02"
```

### Run the backend as a systemd user service

Copy the template into your user units directory, edit the workspace path, then
enable it:

```sh
mkdir -p ~/.config/systemd/user
cp packaging/systemd/ledger-flow.service ~/.config/systemd/user/
$EDITOR ~/.config/systemd/user/ledger-flow.service
systemctl --user daemon-reload
systemctl --user enable --now ledger-flow.service
```

The template runs the same command you can run by hand:

```sh
ledger-flow server --workspace /path/to/ledger-flow-workspace --host 127.0.0.1 --port 8000
```

Useful service commands:

```sh
systemctl --user status ledger-flow.service
journalctl --user -u ledger-flow.service -f
systemctl --user restart ledger-flow.service
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [ROADMAP.md](ROADMAP.md)
- [DECISIONS.md](DECISIONS.md)
