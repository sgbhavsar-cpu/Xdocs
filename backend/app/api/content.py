"""Content read endpoints (API Spec §4)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
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
    locale: Annotated[str | None, Query()] = None,
) -> PageOut:
    page = await service.get_page(session, page_id, user, locale=locale)
    return PageOut.model_validate(page)
