"""baseline: enable required Postgres extensions

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-25

Enables the extensions the data model depends on (Data Model §1). The content
schema (spaces/books/pages/...) is introduced in migration 0001's successors
during Epic B.
"""

from __future__ import annotations

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
