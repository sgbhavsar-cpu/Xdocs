#!/usr/bin/env bash
# Provisions the Xdocs dev container: env, backend deps, frontend build, seed data.
set -e
cd /workspace

# Default config (offline: mock LLM + mock PDF).
[ -f .env ] || cp .env.example .env

echo "==> Installing backend (Python) dependencies"
python -m pip install --upgrade pip >/dev/null
pip install -e "backend/.[dev]"

echo "==> Installing + building frontend"
corepack enable && corepack prepare pnpm@9 --activate
(cd frontend && pnpm install && pnpm build)

# The `api` service applies migrations on startup; wait for them, then seed
# (idempotent). Avoids running alembic twice (no migration race).
echo "==> Seeding demo content"
(
  cd backend
  for _ in $(seq 1 30); do
    if python -m app.scripts.seed; then break; fi
    echo "    waiting for the database/migrations…"
    sleep 2
  done
)

echo ""
echo "✅ Xdocs is ready. Open the demo: http://localhost:8080  (API docs: http://localhost:8000/docs)"
