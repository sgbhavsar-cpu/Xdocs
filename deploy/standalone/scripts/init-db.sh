#!/usr/bin/env bash
# Apply the Docs_-prefixed schema to an existing PostgreSQL (bring-your-own-DB).
#
#   PGURL="postgresql://user:pass@host:5432/dbname" ./scripts/init-db.sh
#
# Requires `psql`. The database must have the `vector`, `pg_trgm`, and `pgcrypto`
# extensions available (the schema enables them).
set -euo pipefail

PGURL="${PGURL:-${1:-}}"
if [[ -z "${PGURL}" ]]; then
  echo "usage: PGURL=postgresql://user:pass@host:5432/db ./scripts/init-db.sh" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Applying ${HERE}/schema.sql to ${PGURL%%\?*} ..."
psql "${PGURL}" -v ON_ERROR_STOP=1 -f "${HERE}/schema.sql"
echo "Done. Start the API with DB_TABLE_PREFIX=Docs_."
