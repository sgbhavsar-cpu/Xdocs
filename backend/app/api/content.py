"""Content read endpoints (API Spec §4)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.content import service
from app.content.schemas import PageOut, SpaceListOut, TreeOut
from app.core.db import get_session

router = APIRouter(tags=["content"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/spaces", response_model=SpaceListOut)
async def list_spaces(session: Session, user: CurrentUser) -> SpaceListOut:
    items = await service.list_spaces(session, user)
    return SpaceListOut.model_validate({"items": items})


@router.get("/spaces/{slug}/tree", response_model=TreeOut)
async def space_tree(
    slug: str,
    session: Session,
    user: CurrentUser,
    version: Annotated[str | None, Query()] = None,
    locale: Annotated[str | None, Query()] = None,
) -> TreeOut:
    tree = await service.get_tree(session, slug, user, version_label=version, locale=locale)
    return TreeOut.model_validate(tree)


@router.get("/pages/{page_id}", response_model=PageOut)
async def get_page(
    page_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    request: Request,
    response: Response,
    locale: Annotated[str | None, Query()] = None,
) -> PageOut | Response:
    page = await service.get_page(session, page_id, user, locale=locale)
    etag = page.pop("etag")
    # Conditional GET: skip the body when the client already has this revision (H3).
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=30"
    return PageOut.model_validate(page)
