[group("App commands")]
app-backend:
    cd app/backend && uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000

[group("App commands")]
app-frontend:
    cd app/frontend && pnpm dev
