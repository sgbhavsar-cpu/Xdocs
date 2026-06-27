# Xdocs standalone deployment package

Deploy the Xdocs API and its dependencies on your own infrastructure. The
database schema uses **`Docs_`-prefixed** tables so it can live alongside other
tables in a shared PostgreSQL database. The application targets these tables when
started with `DB_TABLE_PREFIX=Docs_`.

> This package is self-contained and does **not** use Alembic — the schema is
> created from [`schema.sql`](./schema.sql), which is generated directly from the
> ORM models (so it always matches the application).

## Contents

| File | Purpose |
| --- | --- |
| `schema.sql` | PostgreSQL DDL: all tables prefixed `Docs_`, extensions, indexes, FTS index |
| `docker-compose.standalone.yml` | One-command Postgres + Redis + MinIO + API |
| `.env.example` | Configuration template (copy to `.env`) |
| `scripts/init-db.sh` | Apply `schema.sql` to an existing PostgreSQL |
| `scripts/init-minio.sh` | Create the media bucket on an existing MinIO/S3 |
| `scripts/run-api.sh` | Run the API on a bare-metal/VM host |
| `generate_schema.py` | Regenerate `schema.sql` from the models |

## Option A — Docker Compose (everything)

```bash
cd deploy/standalone
cp .env.example .env          # edit secrets, JWKS_URL, CORS_ALLOWED_ORIGINS
docker compose -f docker-compose.standalone.yml up -d --build
```

Postgres applies `schema.sql` on first start; the API boots with
`DB_TABLE_PREFIX=Docs_` and serves on `:8000`. MinIO is on `:9000` (console
`:9001`) and its bucket is created by the `minio-init` one-shot service.

## Option B — Bring your own infrastructure

1. **Database** — apply the schema to your PostgreSQL (needs the `vector`,
   `pg_trgm`, `pgcrypto` extensions available):

   ```bash
   PGURL="postgresql://user:pass@db-host:5432/yourdb" ./scripts/init-db.sh
   ```

2. **Object storage** (optional; media is stored in the DB in v1) — create a
   bucket on your MinIO/S3:

   ```bash
   MINIO_ENDPOINT=http://minio-host:9000 MINIO_ROOT_USER=… \
   MINIO_ROOT_PASSWORD=… MINIO_BUCKET=xdocs-media ./scripts/init-minio.sh
   ```

3. **API** — point it at your Postgres/Redis and run with the prefix:

   ```bash
   cd backend
   export DATABASE_URL="postgresql+asyncpg://user:pass@db-host:5432/yourdb"
   export DB_TABLE_PREFIX=Docs_ REDIS_URL="redis://redis-host:6379/0"
   export JWKS_URL=… JWT_ISSUER=… JWT_AUDIENCE=xdocs CORS_ALLOWED_ORIGINS=…
   ../deploy/standalone/scripts/run-api.sh
   ```

   (A `systemd` unit can wrap `run-api.sh`; set the same environment in the unit.)

## Regenerating the schema

Whenever the models change, regenerate the DDL so it stays in sync:

```bash
cd backend
DB_TABLE_PREFIX=Docs_ python ../deploy/standalone/generate_schema.py \
  > ../deploy/standalone/schema.sql
```

## Notes

- `DB_TABLE_PREFIX` defaults to empty in the main app (its tables are unprefixed
  and managed by Alembic). It only needs `Docs_` for this standalone schema.
- The bundled `vector`/`pg_trgm` extensions back the documented scale-out search
  path; v1 keyword + semantic search runs in the application, so the API is fully
  functional without additional tuning.
