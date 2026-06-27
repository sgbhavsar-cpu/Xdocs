"""Generate the standalone PostgreSQL schema (Docs_-prefixed) from the ORM models.

Run from the backend venv:

    DB_TABLE_PREFIX=Docs_ python deploy/standalone/generate_schema.py > deploy/standalone/schema.sql

The output is committed as `schema.sql`. Because it is generated directly from
`Base.metadata`, it always matches the application models. The app targets these
tables when started with the same `DB_TABLE_PREFIX` (see README).
"""

from __future__ import annotations

import os

# The prefix must be set before importing the app so model __tablename__ pick it up.
PREFIX = os.environ.setdefault("DB_TABLE_PREFIX", "Docs_")

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

import app.models  # noqa: E402,F401  (registers every model on Base.metadata)
from app.core.db import Base  # noqa: E402

_PG = postgresql.dialect()


def main() -> None:
    chunk = f"{PREFIX}doc_chunk"
    print(f"-- Xdocs standalone schema (tables prefixed '{PREFIX}').")
    print("-- Generated from the ORM models - do not edit by hand.")
    print("-- Regenerate: DB_TABLE_PREFIX=Docs_ python deploy/standalone/generate_schema.py\n")

    print("CREATE EXTENSION IF NOT EXISTS vector;")
    print("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    print("CREATE EXTENSION IF NOT EXISTS pgcrypto;\n")

    for table in Base.metadata.sorted_tables:
        print(str(CreateTable(table).compile(dialect=_PG)).strip() + ";\n")
        for index in table.indexes:
            print(str(CreateIndex(index).compile(dialect=_PG)).strip() + ";")
        if table.indexes:
            print()

    # Keyword-search acceleration (Postgres FTS), matching migration 0003.
    print(
        f'CREATE INDEX IF NOT EXISTS "ix_{chunk}_ts" '
        f'ON "{chunk}" USING gin (to_tsvector(\'simple\', content));'
    )


if __name__ == "__main__":
    main()
