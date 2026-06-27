"""Admin / CMS endpoints (API Spec §9). Permission checks live in the service."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin import service
from app.admin.schemas import (
    CloneVersionReq,
    CreateBookInSpaceReq,
    CreateBookReq,
    CreatePageReq,
    CreateSectionReq,
    CreateSpaceReq,
    CreateVersionReq,
    DraftReq,
    PreviewOut,
    PreviewReq,
    ReorderReq,
    SaveTranslationReq,
    UpdateBookReq,
    UpdatePageReq,
    UpdateSectionReq,
    UpdateSpaceReq,
    UpdateVersionReq,
)
from app.auth.deps import CurrentUser
from app.content.render import render_markdown
from app.core.db import get_session

router = APIRouter(tags=["admin"], prefix="/admin")

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/preview", response_model=PreviewOut)
async def preview(req: PreviewReq, user: CurrentUser) -> PreviewOut:
    html, headings = render_markdown(req.markdown, source_map=True)
    return PreviewOut(html=html, headings=headings)


@router.post("/spaces")
async def create_space(req: CreateSpaceReq, session: Session, user: CurrentUser) -> dict[str, Any]:
    space = await service.create_space(
        session,
        user,
        slug=req.slug,
        title=req.title,
        default_locale=req.default_locale,
        description=req.description,
        color=req.color,
    )
    return {"id": space.id, "slug": space.slug, "color": space.color}


@router.get("/spaces")
async def list_spaces(session: Session, user: CurrentUser) -> dict[str, Any]:
    return {"items": await service.list_admin_spaces(session, user)}


@router.put("/spaces/{slug}")
async def update_space(
    slug: str, req: UpdateSpaceReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    space = await service.update_space(
        session,
        user,
        slug,
        title=req.title,
        description=req.description,
        color=req.color,
        default_locale=req.default_locale,
    )
    return {"id": space.id, "slug": space.slug, "color": space.color}


@router.delete("/spaces/{slug}", status_code=204)
async def delete_space(slug: str, session: Session, user: CurrentUser) -> None:
    await service.delete_space(session, user, slug)


@router.get("/spaces/{slug}/archive")
async def archive_space(slug: str, session: Session, user: CurrentUser) -> Response:
    name, data = await service.archive_space(session, user, slug)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


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


@router.post("/spaces/{slug}/books")
async def create_book_in_space(
    slug: str, req: CreateBookInSpaceReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    book = await service.create_book_in_space(session, user, space_slug=slug, title=req.title)
    return {"id": book.id, "slug": book.slug, "title": book.title}


@router.post("/spaces/{slug}/books/import-pdf")
async def import_pdf_book(
    slug: str,
    session: Session,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    locale: Annotated[str, Form()] = "en",
) -> dict[str, Any]:
    """Create a new book from a PDF (its sections become draft pages)."""
    data = await file.read()
    result = await service.import_pdf_as_book(
        session, user, space_slug=slug, data=data, filename=file.filename or "document.pdf",
        locale=locale,
    )
    return {**result, "count": len(result["pages"])}


@router.post("/spaces/{slug}/import-pdf-markdown")
async def import_pdf_markdown(
    slug: str,
    session: Session,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Parse a PDF and return its Markdown for insertion into the open page (F7)."""
    data = await file.read()
    return await service.import_pdf_as_markdown(
        session, user, space_slug=slug, data=data, filename=file.filename or "document.pdf"
    )


@router.put("/books/{book_id}")
async def update_book(
    book_id: uuid.UUID, req: UpdateBookReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    book = await service.update_book(session, user, book_id, title=req.title)
    return {"id": book.id, "title": book.title}


@router.delete("/books/{book_id}", status_code=204)
async def delete_book(book_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_book(session, user, book_id)


@router.get("/books/{book_id}/archive")
async def archive_book(book_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    name, data = await service.archive_book(session, user, book_id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/sections")
async def create_section(
    req: CreateSectionReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    section = await service.create_section(session, user, book_id=req.book_id, title=req.title)
    return {"id": section.id, "slug": section.slug, "title": section.title}


@router.put("/sections/{section_id}")
async def update_section(
    section_id: uuid.UUID, req: UpdateSectionReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    section = await service.update_section(session, user, section_id, title=req.title)
    return {"id": section.id, "title": section.title}


@router.delete("/sections/{section_id}", status_code=204)
async def delete_section(section_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_section(session, user, section_id)


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
        section_id=req.section_id,
        markdown=req.markdown,
        sort_order=req.sort_order,
    )
    return {"id": page.id, "slug": page.slug, "status": page.status}


@router.put("/pages/{page_id}")
async def update_page(
    page_id: uuid.UUID, req: UpdatePageReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    return await service.update_page(
        session, user, page_id, title=req.title, slug=req.slug, locale=req.locale
    )


@router.post("/import/pdf")
async def import_pdf(
    session: Session,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    book_id: Annotated[uuid.UUID, Form()],
    locale: Annotated[str, Form()] = "en",
    parent_page_id: Annotated[uuid.UUID | None, Form()] = None,
) -> dict[str, Any]:
    """Import a PDF as one or more draft pages under a book (F7)."""
    data = await file.read()
    pages = await service.import_pdf_document(
        session,
        user,
        book_id=book_id,
        data=data,
        filename=file.filename or "document.pdf",
        locale=locale,
        parent_page_id=parent_page_id,
    )
    return {"pages": pages, "count": len(pages)}


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


@router.post("/pages/{page_id}/unpublish")
async def unpublish(page_id: uuid.UUID, session: Session, user: CurrentUser) -> dict[str, Any]:
    return await service.unpublish_page(session, user, page_id)


@router.post("/pages/{page_id}/discard-draft")
async def discard_draft(
    page_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    locale: Annotated[str, Query()] = "en",
) -> dict[str, Any]:
    return await service.discard_draft(session, user, page_id, locale)


@router.get("/pages/{page_id}/revisions/{revision}")
async def get_revision(
    page_id: uuid.UUID,
    revision: int,
    session: Session,
    user: CurrentUser,
    locale: Annotated[str, Query()] = "en",
) -> dict[str, Any]:
    return await service.get_revision(session, user, page_id, locale, revision)


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


# ---- Versions (G1/G2) ----


@router.post("/versions")
async def create_version(
    req: CreateVersionReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    v = await service.create_version(
        session,
        user,
        space_id=req.space_id,
        label=req.label,
        visibility=req.visibility,
        sort_order=req.sort_order,
    )
    return {"id": v.id, "label": v.label, "visibility": v.visibility, "is_default": v.is_default}


@router.put("/versions/{version_id}")
async def update_version(
    version_id: uuid.UUID, req: UpdateVersionReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    v = await service.update_version(
        session, user, version_id, visibility=req.visibility, is_default=req.is_default
    )
    return {"id": v.id, "label": v.label, "visibility": v.visibility, "is_default": v.is_default}


@router.post("/versions/{version_id}/clone")
async def clone_version(
    version_id: uuid.UUID, req: CloneVersionReq, session: Session, user: CurrentUser
) -> dict[str, Any]:
    v = await service.clone_version(session, user, version_id, new_label=req.label)
    return {"id": v.id, "label": v.label, "visibility": v.visibility}


# ---- LLM-assisted translation (G4) ----


@router.post("/pages/{page_id}/translations/{locale}/draft")
async def translation_draft(
    page_id: uuid.UUID,
    locale: str,
    req: DraftReq,
    session: Session,
    user: CurrentUser,
) -> dict[str, Any]:
    return await service.generate_translation_draft(
        session, user, page_id=page_id, locale=locale, source_locale=req.source_locale
    )


@router.post("/pages/{page_id}/translations/{locale}/approve")
async def translation_approve(
    page_id: uuid.UUID, locale: str, session: Session, user: CurrentUser
) -> dict[str, Any]:
    return await service.approve_translation(session, user, page_id, locale)
