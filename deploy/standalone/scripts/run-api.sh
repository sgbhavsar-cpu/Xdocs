#!/usr/bin/env bash
# Run the Xdocs API on a bare-metal/VM host (no Docker), targeting the
# Docs_-prefixed schema. Run after init-db.sh has created the schema.
#
#   cd backend
#   ../deploy/standalone/scripts/run-api.sh
#
# Reads configuration from the environment / an .env in the backend dir.
set -euo pipefail

REPO_BACKEND="${REPO_BACKEND:-$(pwd)}"
cd "${REPO_BACKEND}"

export DB_TABLE_PREFIX="${DB_TABLE_PREFIX:-Docs_}"
: "${DATABASE_URL:?set DATABASE_URL (postgresql+asyncpg://...)}"

python -m pip install -e .
# Schema is managed by schema.sql (init-db.sh) — do NOT run alembic here.
exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" \
  --workers "${API_WORKERS:-2}"
