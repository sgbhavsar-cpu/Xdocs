"""Media asset model (F5).

For v1 the bytes live in the row (target scale); the storage layer can move to
S3/MinIO without changing the API (design §4.4).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.content import TimestampMixin


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_asset"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("space.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
