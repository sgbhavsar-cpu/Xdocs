"""export: export_job

Revision ID: 0005_export
Revises: 0004_llm
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_export"
down_revision = "0004_llm"
branch_labels = None
depends_on = None

_ts = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "export_job",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", _ts, nullable=False),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("export_job")
