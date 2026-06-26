"""Admin / CMS endpoints (API Spec §9). Permission checks live in the service."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import service
from app.admin.schemas import (
    CreateBookReq,
    CreatePageReq,
    CreateSpaceReq,
    PreviewOut,
    PreviewReq,
    ReorderReq,
    SaveTranslationReq,
)
from app.auth.deps import CurrentUser
from app.content.render import render_markdown
from app.core.db import get_session

router = APIRouter(tags=["admin"], prefix="/admin")

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/preview", response_model=PreviewOut)
async def preview(req: PreviewReq, user: CurrentUser) -> PreviewOut:
    html, headings = render_markdown(req.markdown)
    return PreviewOut(html=html, headings=headings)


@router.post("/spaces")
async def create_space(req: CreateSpaceReq, session: Session, user: CurrentUser) -> dict[str, Any]:
    space = await service.create_space(
        session, user, slug=req.slug, title=req.title, default_locale=req.default_locale
    )
    return {"id": space.id, "slug": space.slug}


@router.get("/spaces/{slug}/tree")
async def admin_tree(slug: str, session: Session, user: CurrentUser) -> dict[str, Any]:
    return await service.admin_tree(session, user, slug)


@router.post("/books")
async def create_book(req: CreateBookReq, session: Session, user: CurrentUser) -> dict[str, Any]:
    book = await service.create_book(
        session,
        user,
        space_id=req.space_id,
        version_id=req.version_id,
        slug=req.slug,
        title=req.title,
        sort_order=req.sort_order,
    )
    return {"id": book.id, "slug": book.slug}


@router.post("/pages")
async def create_page(req: CreatePageReq, session: Session, user: CurrentUser) -> dict[str, Any]:
    page = await service.create_page(
        session,
        user,
        book_id=req.book_id,
        slug=req.slug,
        title=req.title,
        locale=req.locale,
        parent_page_id=req.parent_page_id,
        markdown=req.markdown,
        sort_order=req.sort_order,
    )
    return {"id": page.id, "slug": page.slug, "status": page.status}


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(page_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_page(session, user, page_id)


@router.post("/pages/reorder", status_code=204)
async def reorder(req: ReorderReq, session: Session, user: CurrentUser) -> None:
    await service.reorder_pages(session, user, [i.model_dump() for i in req.items])


@router.get("/pages/{page_id}/translations/{locale}")
async def get_translation(
    page_id: uuid.UUID, locale: str, session: Session, user: CurrentUser
) -> dict[str, Any]:
    return await service.get_translation(session, user, page_id, locale)


@router.put("/pages/{page_id}/translations/{locale}")
async def save_translation(
    page_id: uuid.UUID,
    locale: str,
    req: SaveTranslationReq,
    session: Session,
    user: CurrentUser,
) -> dict[str, Any]:
    return await service.save_translation(
        session,
        user,
        page_id=page_id,
        locale=locale,
        markdown=req.markdown,
        base_revision=req.base_revision,
        title=req.title,
    )


@router.post("/pages/{page_id}/publish")
async def publish(
    page_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    locale: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    return await service.publish_page(session, user, page_id, locale=locale)


@router.get("/pages/{page_id}/revisions")
async def revisions(
    page_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    locale: Annotated[str, Query()] = "en",
) -> dict[str, Any]:
    return {"items": await service.list_revisions(session, user, page_id, locale)}


@router.post("/pages/{page_id}/revisions/{revision}/restore")
async def restore(
    page_id: uuid.UUID,
    revision: int,
    session: Session,
    user: CurrentUser,
    locale: Annotated[str, Query()] = "en",
) -> dict[str, Any]:
    return await service.restore_revision(session, user, page_id, locale, revision)
