"""llm: artifacts, translation cache, analytics events

Revision ID: 0004_llm
Revises: 0003_search
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_llm"
down_revision = "0003_search"
branch_labels = None
depends_on = None

_ts = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "llm_artifact",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", _ts, nullable=False),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
    )

    op.create_table(
        "translation_cache",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("expires_at", _ts, nullable=False),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("page_id", "revision", "locale", name="uq_translation_cache"),
    )
    op.create_index("ix_translation_cache_page", "translation_cache", ["page_id"])

    op.create_table(
        "analytics_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
    )
    op.create_index("ix_analytics_event_type", "analytics_event", ["type"])


def downgrade() -> None:
    op.drop_index("ix_analytics_event_type", table_name="analytics_event")
    op.drop_table("analytics_event")
    op.drop_index("ix_translation_cache_page", table_name="translation_cache")
    op.drop_table("translation_cache")
    op.drop_table("llm_artifact")
