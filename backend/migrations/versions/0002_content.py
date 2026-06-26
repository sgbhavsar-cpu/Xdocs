"""content schema: spaces, versions, books, pages, translations, revisions

Revision ID: 0002_content
Revises: 0001_baseline
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_content"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_ts = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "space",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_locale", sa.String(16), nullable=False),
        sa.Column("landing_blocks", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("slug", name="uq_space_slug"),
    )
    op.create_index("ix_space_slug", "space", ["slug"])

    op.create_table(
        "product_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("space.id", ondelete="CASCADE")),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("space_id", "label", name="uq_version_space_label"),
    )

    op.create_table(
        "book",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("space.id", ondelete="CASCADE")),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("product_version.id", ondelete="CASCADE")),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("version_id", "slug", name="uq_book_version_slug"),
    )

    op.create_table(
        "page",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(), sa.ForeignKey("book.id", ondelete="CASCADE")),
        sa.Column(
            "parent_page_id", sa.Uuid(), sa.ForeignKey("page.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("book_id", "parent_page_id", "slug", name="uq_page_parent_slug"),
    )
    op.create_index("ix_page_tree", "page", ["book_id", "parent_page_id", "sort_order"])

    op.create_table(
        "page_translation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("page_id", sa.Uuid(), sa.ForeignKey("page.id", ondelete="CASCADE")),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("html_cached", sa.Text(), nullable=True),
        sa.Column("headings", postgresql.JSONB(), nullable=True),
        sa.Column("translation_status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_at", _ts, nullable=True),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("page_id", "locale", name="uq_translation_page_locale"),
    )

    op.create_table(
        "page_revision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "page_translation_id",
            sa.Uuid(),
            sa.ForeignKey("page_translation.id", ondelete="CASCADE"),
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
        sa.UniqueConstraint("page_translation_id", "revision", name="uq_revision_translation_rev"),
    )


def downgrade() -> None:
    op.drop_table("page_revision")
    op.drop_table("page_translation")
    op.drop_index("ix_page_tree", table_name="page")
    op.drop_table("page")
    op.drop_table("book")
    op.drop_table("product_version")
    op.drop_index("ix_space_slug", table_name="space")
    op.drop_table("space")
