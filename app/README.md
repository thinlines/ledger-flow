# Ledger Workflow MVP

This app adds a local GUI for CSV import and unknown-account reconciliation.

## Components

- `app/backend`: FastAPI API that wraps existing ledger scripts.
- `app/frontend`: SvelteKit UI.

## Run backend

```bash
cd app/backend
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Run frontend

```bash
cd app/frontend
pnpm install
pnpm dev
```

Frontend expects backend at `http://127.0.0.1:8000` and proxies `/api`.
