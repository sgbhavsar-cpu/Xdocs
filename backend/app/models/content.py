"""Content model: Spaces -> Versions/Books -> Pages -> Translations -> Revisions.

Types are kept portable (Uuid/JSON/DateTime) so the same models run on Postgres
in production and SQLite in fast integration tests. The Postgres-specific schema
(extensions, pgvector) lives in the Alembic migrations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, t


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Space(Base, TimestampMixin):
    __tablename__ = t("space")

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Reserved multi-tenant seam (single-tenant v1, design §16.6).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_locale: Mapped[str] = mapped_column(String(16), default="en")
    # Optional accent colour (hex, e.g. "#0b5cad") shown on portal/admin cards.
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    landing_blocks: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ProductVersion(Base, TimestampMixin):
    __tablename__ = t("product_version")
    __table_args__ = (UniqueConstraint("space_id", "label", name="uq_version_space_label"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(t("space.id"), ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(64))
    # "internal" | "published" — readers only see published (design §16.5).
    visibility: Mapped[str] = mapped_column(String(16), default="published")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Book(Base, TimestampMixin):
    __tablename__ = t("book")
    __table_args__ = (UniqueConstraint("version_id", "slug", name="uq_book_version_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(t("space.id"), ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(t("product_version.id"), ondelete="CASCADE")
    )
    slug: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(256))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Section(Base, TimestampMixin):
    """A sub-heading grouping of pages inside a Book (above the page list).

    Optional: a page may sit directly under its book (``section_id`` null) or
    inside a section. Deleting a section ungroups its pages rather than deleting
    them (handled in the service, so it works on SQLite too)."""

    __tablename__ = t("section")
    __table_args__ = (UniqueConstraint("book_id", "slug", name="uq_section_book_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(t("book.id"), ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(256))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Page(Base, TimestampMixin):
    __tablename__ = t("page")
    __table_args__ = (
        UniqueConstraint("book_id", "parent_page_id", "slug", name="uq_page_parent_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(t("book.id"), ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(t("section.id"), ondelete="SET NULL"), nullable=True
    )
    parent_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(t("page.id"), ondelete="CASCADE"), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(128))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="published")  # draft | published


class PageTranslation(Base, TimestampMixin):
    __tablename__ = t("page_translation")
    __table_args__ = (UniqueConstraint("page_id", "locale", name="uq_translation_page_locale"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(t("page.id"), ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(512))
    # `markdown` is the working draft; `published_markdown` is the last published
    # snapshot served to readers. They diverge when a published page is edited but
    # not yet re-published (the "two rows: Published + Draft" workflow).
    markdown: Mapped[str] = mapped_column(Text)
    published_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_cached: Mapped[str | None] = mapped_column(Text, nullable=True)
    headings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # human | llm_draft | approved
    translation_status: Mapped[str] = mapped_column(String(16), default="human")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    published_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocChunk(Base, TimestampMixin):
    """Search/RAG unit (C1). Denormalizes space/book/page/locale/title so search
    can filter by scope/ACL and group results without multi-table joins. The
    embedding is stored portably as JSON; on Postgres a GIN index on a tsvector of
    `content` accelerates keyword search (migration 0003). The pgvector/HNSW path
    is the documented scale-out (design §5)."""

    __tablename__ = t("doc_chunk")

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    page_translation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(t("page_translation.id"), ondelete="CASCADE")
    )
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    space_slug: Mapped[str] = mapped_column(String(128), index=True)
    book_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    locale: Mapped[str] = mapped_column(String(16))
    page_title: Mapped[str] = mapped_column(String(512))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    anchor: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)


class PageRevision(Base, TimestampMixin):
    __tablename__ = t("page_revision")
    __table_args__ = (
        UniqueConstraint("page_translation_id", "revision", name="uq_revision_translation_rev"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    page_translation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(t("page_translation.id"), ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    markdown: Mapped[str] = mapped_column(Text)
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
