"""media: media_asset

Revision ID: 0006_media
Revises: 0005_export
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_media"
down_revision = "0005_export"
branch_labels = None
depends_on = None

_ts = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "media_asset",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "space_id", sa.Uuid(), sa.ForeignKey("space.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("media_asset")
