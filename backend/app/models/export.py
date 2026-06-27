"""Export job model (PDF export, Epic E)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, t
from app.models.content import TimestampMixin


class ExportJob(Base, TimestampMixin):
    """A PDF export request and its rendered output.

    For v1 the rendered PDF is stored in the row (target scale); the storage
    adapter can move to S3/MinIO for larger documents without API changes.
    """

    __tablename__ = t("export_job")

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(16))  # page | book | space | artifact
    scope_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="queued"
    )  # queued|rendering|done|failed
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    content_type: Mapped[str] = mapped_column(String(64), default="application/pdf")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
