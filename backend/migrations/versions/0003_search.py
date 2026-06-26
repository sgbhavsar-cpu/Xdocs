"""search index: doc_chunk

Revision ID: 0003_search
Revises: 0002_content
Create Date: 2026-06-25

Creates the denormalized search-unit table. The embedding is stored as JSONB for
portability; a GIN index over a tsvector of `content` accelerates keyword search
on Postgres. The pgvector/HNSW column + index is the documented scale-out path
(design §5) and is added when the query layer switches to DB-native similarity.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_search"
down_revision = "0002_content"
branch_labels = None
depends_on = None

_ts = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "doc_chunk",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "page_translation_id",
            sa.Uuid(),
            sa.ForeignKey("page_translation.id", ondelete="CASCADE"),
        ),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("space_slug", sa.String(128), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("page_title", sa.String(512), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("anchor", postgresql.JSONB(), nullable=True),
        sa.Column("embedding", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", _ts, nullable=False),
        sa.Column("updated_at", _ts, nullable=False),
    )
    op.create_index("ix_doc_chunk_page", "doc_chunk", ["page_id"])
    op.create_index("ix_doc_chunk_space", "doc_chunk", ["space_slug"])
    op.create_index("ix_doc_chunk_book", "doc_chunk", ["book_id"])
    # Keyword search acceleration (Postgres FTS).
    op.execute(
        "CREATE INDEX ix_doc_chunk_ts ON doc_chunk USING gin (to_tsvector('simple', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_doc_chunk_ts")
    op.drop_index("ix_doc_chunk_book", table_name="doc_chunk")
    op.drop_index("ix_doc_chunk_space", table_name="doc_chunk")
    op.drop_index("ix_doc_chunk_page", table_name="doc_chunk")
    op.drop_table("doc_chunk")
