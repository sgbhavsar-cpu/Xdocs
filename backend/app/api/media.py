"""Media upload/serve endpoints (F5, API Spec §8)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.auth.permissions import Permission
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError, PayloadTooLargeError, ValidationError
from app.models.content import Space
from app.models.media import MediaAsset

router = APIRouter(tags=["media"])

Session = Annotated[AsyncSession, Depends(get_session)]

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}


@router.post("/media")
async def upload_media(
    session: Session,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    space: Annotated[str, Form()],
) -> dict[str, Any]:
    if not user.can(space, Permission.WRITE):
        raise ForbiddenError("Insufficient permission.", details={"space": space})
    if file.content_type not in _ALLOWED:
        raise ValidationError(
            "Unsupported media type.", details={"content_type": file.content_type}
        )
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise PayloadTooLargeError("File exceeds the size limit.", details={"max": _MAX_BYTES})

    space_row = (
        await session.execute(select(Space).where(Space.slug == space))
    ).scalar_one_or_none()
    asset = MediaAsset(
        space_id=space_row.id if space_row else None,
        filename=file.filename or "upload",
        content_type=file.content_type,
        size=len(data),
        content=data,
        uploaded_by=_as_uuid(user.sub),
    )
    session.add(asset)
    await session.commit()
    return {
        "id": asset.id,
        "url": f"/api/v1/media/{asset.id}",
        "content_type": asset.content_type,
        "size": asset.size,
    }


@router.get("/media/{media_id}")
async def serve_media(media_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    asset = (
        await session.execute(select(MediaAsset).where(MediaAsset.id == media_id))
    ).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("Media not found.", details={"id": str(media_id)})
    return Response(content=asset.content, media_type=asset.content_type)


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
