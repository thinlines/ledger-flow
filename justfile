[group("App commands")]
app-backend:
    cd app/backend && uv run uvicorn main:app --reload --host "${LEDGER_FLOW_BACKEND_HOST:-127.0.0.1}" --port "${LEDGER_FLOW_BACKEND_PORT:-8000}"

[group("App commands")]
app-frontend:
    cd app/frontend && pnpm dev --host "${LEDGER_FLOW_FRONTEND_HOST:-127.0.0.1}"

# Start frontend + backend servers for a named worktree slot (aristotle | hypatia | spinoza).
# Each slot gets fixed ports so they don't collide with the main dev server.
[group("App commands")]
worktree-servers worktree_name:
    #!/usr/bin/env bash
    set -e
    case "{{worktree_name}}" in
      aristotle) backend_port=8001; frontend_port=5174 ;;
      hypatia)   backend_port=8002; frontend_port=5175 ;;
      spinoza)   backend_port=8003; frontend_port=5176 ;;
      *) echo "Unknown worktree: {{worktree_name}} (expected aristotle | hypatia | spinoza)"; exit 1 ;;
    esac
    worktree=".claude/worktrees/{{worktree_name}}"
    export LEDGER_FLOW_BACKEND_PORT=$backend_port
    export LEDGER_FLOW_FRONTEND_PORT=$frontend_port
    just --justfile "$worktree/justfile" --working-directory "$worktree" app-backend &
    just --justfile "$worktree/justfile" --working-directory "$worktree" app-frontend
