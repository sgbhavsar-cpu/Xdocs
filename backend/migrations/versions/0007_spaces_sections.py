"""spaces: space.color, section, page.section_id

Revision ID: 0007_spaces_sections
Revises: 0006_media
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_spaces_sections"
down_revision = "0006_media"
branch_labels = None
depends_on = None

_ts = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("space", sa.Column("color", sa.String(16), nullable=True))

    op.create_table(
        "section",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(), sa.ForeignKey("book.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("book_id", "slug", name="uq_section_book_slug"),
    )

    op.add_column(
        "page",
        sa.Column(
            "section_id",
            sa.Uuid(),
            sa.ForeignKey("section.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("page", "section_id")
    op.drop_table("section")
    op.drop_column("space", "color")
