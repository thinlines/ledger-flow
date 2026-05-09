[group("App commands")]
app-backend:
    cd app/backend && uv run uvicorn main:app --reload --host "${LEDGER_FLOW_BACKEND_HOST:-127.0.0.1}" --port 8000

[group("App commands")]
app-frontend:
    cd app/frontend && pnpm dev --host "${LEDGER_FLOW_FRONTEND_HOST:-127.0.0.1}"
