"""LLM-related persistence: ephemeral artifacts, translation cache, analytics."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.content import TimestampMixin


class LlmArtifact(Base, TimestampMixin):
    """Ephemeral, download-only output of summarize/extract (design §6.3)."""

    __tablename__ = "llm_artifact"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32))  # summary | extract
    markdown: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TranslationCache(Base, TimestampMixin):
    """On-the-fly LLM translation, cached per page-revision × locale (design §16.3)."""

    __tablename__ = "translation_cache"
    __table_args__ = (
        UniqueConstraint("page_id", "revision", "locale", name="uq_translation_cache"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(String(16))
    html: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnalyticsEvent(Base, TimestampMixin):
    """Minimal product analytics (design §10). LLM feedback lands here in v1."""

    __tablename__ = "analytics_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    type: Mapped[str] = mapped_column(String(32), index=True)  # page_view | llm_feedback | search
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
