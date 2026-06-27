"""draft/publish: page_translation.published_markdown + published_revision

Revision ID: 0008_published_snapshot
Revises: 0007_spaces_sections
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_published_snapshot"
down_revision = "0007_spaces_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "page_translation", sa.Column("published_markdown", sa.Text(), nullable=True)
    )
    op.add_column(
        "page_translation", sa.Column("published_revision", sa.Integer(), nullable=True)
    )
    # Backfill the published snapshot for already-published pages so the
    # has-draft comparison (markdown != published_markdown) starts clean.
    op.execute(
        """
        UPDATE page_translation
        SET published_markdown = markdown, published_revision = revision
        WHERE page_id IN (SELECT id FROM page WHERE status = 'published')
        """
    )


def downgrade() -> None:
    op.drop_column("page_translation", "published_revision")
    op.drop_column("page_translation", "published_markdown")
