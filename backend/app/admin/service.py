"""Authoring service (F2–F4, F6): structure CRUD, draft/publish, revisions.

All mutations are permission-checked: WRITE to author within a space, ADMIN to
create/delete spaces. Publishing renders cached HTML + headings and re-indexes
the page for search.
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.admin.import_pdf import parse_pdf
from app.auth.permissions import Permission, Principal
from app.content.render import render_markdown
from app.content.slug import slugify
from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError, RevisionConflictError, ValidationError
from app.models.content import (
    Book,
    DocChunk,
    Page,
    PageRevision,
    PageTranslation,
    ProductVersion,
    Section,
    Space,
)
from app.models.media import MediaAsset
from app.search.service import reindex_page


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _require_global_admin(user: Principal) -> None:
    if user.global_permission != Permission.ADMIN:
        raise ForbiddenError("Admin permission required.")


def _require(user: Principal, space_slug: str, perm: Permission) -> None:
    if not user.can(space_slug, perm):
        raise ForbiddenError("Insufficient permission.", details={"space": space_slug})


async def _space(session: AsyncSession, space_id: uuid.UUID) -> Space:
    s = (await session.execute(select(Space).where(Space.id == space_id))).scalar_one_or_none()
    if s is None:
        raise NotFoundError("Space not found.", details={"space": str(space_id)})
    return s


async def _book(session: AsyncSession, book_id: uuid.UUID) -> Book:
    b = (await session.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
    if b is None:
        raise NotFoundError("Book not found.", details={"book": str(book_id)})
    return b


async def _page(session: AsyncSession, page_id: uuid.UUID) -> Page:
    p = (await session.execute(select(Page).where(Page.id == page_id))).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Page not found.", details={"page": str(page_id)})
    return p


async def _section(session: AsyncSession, section_id: uuid.UUID) -> Section:
    s = (
        await session.execute(select(Section).where(Section.id == section_id))
    ).scalar_one_or_none()
    if s is None:
        raise NotFoundError("Section not found.", details={"section": str(section_id)})
    return s


async def _space_of_page(session: AsyncSession, page: Page) -> Space:
    book = await _book(session, page.book_id)
    return await _space(session, book.space_id)


# ---------------- Spaces / Books / Pages ----------------


async def create_space(
    session: AsyncSession,
    user: Principal,
    *,
    slug: str,
    title: str,
    default_locale: str = "en",
    description: str | None = None,
    color: str | None = None,
) -> Space:
    _require_global_admin(user)
    space = Space(
        slug=slug,
        title=title,
        default_locale=default_locale,
        description=description,
        color=color,
    )
    session.add(space)
    await session.flush()
    # First version, published + default.
    session.add(
        ProductVersion(
            space_id=space.id, label="1.0", visibility="published", is_default=True, sort_order=1
        )
    )
    await session.commit()
    return space


async def list_admin_spaces(session: AsyncSession, user: Principal) -> list[dict[str, Any]]:
    """Spaces the caller may author in, with book/page counts (management grid)."""
    spaces = (await session.execute(select(Space).order_by(Space.title))).scalars()
    out: list[dict[str, Any]] = []
    for space in spaces:
        if not user.can(space.slug, Permission.WRITE):
            continue
        book_ids = list(
            (
                await session.execute(select(Book.id).where(Book.space_id == space.id))
            ).scalars()
        )
        page_count = 0
        if book_ids:
            page_count = len(
                list(
                    (
                        await session.execute(select(Page.id).where(Page.book_id.in_(book_ids)))
                    ).scalars()
                )
            )
        out.append(
            {
                "id": space.id,
                "slug": space.slug,
                "title": space.title,
                "description": space.description,
                "color": space.color,
                "default_locale": space.default_locale,
                "book_count": len(book_ids),
                "page_count": page_count,
            }
        )
    return out


async def update_space(
    session: AsyncSession,
    user: Principal,
    slug: str,
    *,
    title: str | None = None,
    description: str | None = None,
    color: str | None = None,
    default_locale: str | None = None,
) -> Space:
    _require_global_admin(user)
    space = (
        await session.execute(select(Space).where(Space.slug == slug))
    ).scalar_one_or_none()
    if space is None:
        raise NotFoundError("Space not found.", details={"space": slug})
    if title is not None:
        space.title = title
    if description is not None:
        space.description = description
    if color is not None:
        space.color = color
    if default_locale is not None:
        space.default_locale = default_locale
    await session.commit()
    return space


async def delete_space(session: AsyncSession, user: Principal, slug: str) -> None:
    """Delete a space and everything under it. Books/pages/sections/translations
    cascade via FK; search chunks (no FK) and media are removed explicitly so the
    SQLite test path stays consistent with Postgres."""
    _require_global_admin(user)
    space = (
        await session.execute(select(Space).where(Space.slug == slug))
    ).scalar_one_or_none()
    if space is None:
        raise NotFoundError("Space not found.", details={"space": slug})
    await session.execute(delete(DocChunk).where(DocChunk.space_slug == slug))
    await session.execute(delete(MediaAsset).where(MediaAsset.space_id == space.id))
    await session.execute(delete(Space).where(Space.id == space.id))
    await session.commit()


async def archive_space(
    session: AsyncSession, user: Principal, slug: str
) -> tuple[str, bytes]:
    """Export a space to a zip: a manifest, per-page markdown (all locales), and
    every media asset. Authors (WRITE) may archive — it's a read-only export."""
    space = (
        await session.execute(select(Space).where(Space.slug == slug))
    ).scalar_one_or_none()
    if space is None:
        raise NotFoundError("Space not found.", details={"space": slug})
    _require(user, slug, Permission.WRITE)

    books = list(
        (
            await session.execute(
                select(Book).where(Book.space_id == space.id).order_by(Book.sort_order)
            )
        ).scalars()
    )

    buf = io.BytesIO()
    manifest: dict[str, Any] = {
        "space": {
            "slug": space.slug,
            "title": space.title,
            "description": space.description,
            "color": space.color,
            "default_locale": space.default_locale,
        },
        "books": [],
        "exported_at": datetime.now(UTC).isoformat(),
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for book in books:
            manifest["books"].append(await _zip_book(zf, session, book))

        assets = list(
            (
                await session.execute(
                    select(MediaAsset).where(MediaAsset.space_id == space.id)
                )
            ).scalars()
        )
        for asset in assets:
            zf.writestr(f"media/{asset.id}-{asset.filename}", asset.content)

        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

    return f"{slug}.zip", buf.getvalue()


async def _zip_book(zf: zipfile.ZipFile, session: AsyncSession, book: Book) -> dict[str, Any]:
    """Write one book's page markdown into ``zf`` and return its manifest entry."""
    sections = list(
        (
            await session.execute(
                select(Section).where(Section.book_id == book.id).order_by(Section.sort_order)
            )
        ).scalars()
    )
    section_slugs = {s.id: s.slug for s in sections}
    pages = list(
        (
            await session.execute(
                select(Page).where(Page.book_id == book.id).order_by(Page.sort_order)
            )
        ).scalars()
    )
    page_entries: list[dict[str, Any]] = []
    for page in pages:
        trs = list(
            (
                await session.execute(
                    select(PageTranslation).where(PageTranslation.page_id == page.id)
                )
            ).scalars()
        )
        sub = section_slugs.get(page.section_id)
        folder = f"content/{book.slug}" + (f"/{sub}" if sub else "")
        locales = []
        for tr in trs:
            zf.writestr(f"{folder}/{page.slug}.{tr.locale}.md", tr.markdown)
            locales.append(tr.locale)
        page_entries.append(
            {
                "slug": page.slug,
                "title": trs[0].title if trs else page.slug,
                "status": page.status,
                "section": sub,
                "locales": locales,
            }
        )
    return {
        "slug": book.slug,
        "title": book.title,
        "sections": [{"slug": s.slug, "title": s.title} for s in sections],
        "pages": page_entries,
    }


async def archive_book(
    session: AsyncSession, user: Principal, book_id: uuid.UUID
) -> tuple[str, bytes]:
    """Export a single book to a zip (manifest + per-page markdown for all locales)."""
    book = await _book(session, book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        entry = await _zip_book(zf, session, book)
        manifest = {
            "space": {"slug": space.slug, "title": space.title},
            "book": entry,
            "exported_at": datetime.now(UTC).isoformat(),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
    return f"{space.slug}-{book.slug}.zip", buf.getvalue()


async def create_book(
    session: AsyncSession,
    user: Principal,
    *,
    space_id: uuid.UUID,
    version_id: uuid.UUID,
    slug: str,
    title: str,
    sort_order: int = 0,
) -> Book:
    space = await _space(session, space_id)
    _require(user, space.slug, Permission.WRITE)
    book = Book(
        space_id=space_id, version_id=version_id, slug=slug, title=title, sort_order=sort_order
    )
    session.add(book)
    await session.commit()
    return book


async def _default_version(session: AsyncSession, space_id: uuid.UUID) -> ProductVersion:
    """The version new books land in: the default, else the lowest sort_order."""
    versions = list(
        (
            await session.execute(
                select(ProductVersion)
                .where(ProductVersion.space_id == space_id)
                .order_by(ProductVersion.is_default.desc(), ProductVersion.sort_order)
            )
        ).scalars()
    )
    if not versions:
        raise ValidationError("Space has no product version.", details={"space": str(space_id)})
    return versions[0]


async def _space_by_slug(session: AsyncSession, slug: str) -> Space:
    space = (await session.execute(select(Space).where(Space.slug == slug))).scalar_one_or_none()
    if space is None:
        raise NotFoundError("Space not found.", details={"space": slug})
    return space


async def _new_book(session: AsyncSession, space: Space, title: str) -> Book:
    """Create a book under the space's default version with a unique, sorted slug."""
    version = await _default_version(session, space.id)
    existing = {
        s
        for (s,) in (
            await session.execute(select(Book.slug).where(Book.version_id == version.id))
        ).all()
    }
    orders = list(
        (
            await session.execute(select(Book.sort_order).where(Book.version_id == version.id))
        ).scalars()
    )
    book = Book(
        space_id=space.id,
        version_id=version.id,
        slug=slugify(title, existing),
        title=title,
        sort_order=(max(orders) + 1) if orders else 0,
    )
    session.add(book)
    await session.flush()
    return book


async def create_book_in_space(
    session: AsyncSession, user: Principal, *, space_slug: str, title: str
) -> Book:
    """Add a book to a space (resolving the default version + a unique slug)."""
    space = await _space_by_slug(session, space_slug)
    _require(user, space.slug, Permission.WRITE)
    book = await _new_book(session, space, title)
    await session.commit()
    return book


async def update_book(
    session: AsyncSession, user: Principal, book_id: uuid.UUID, *, title: str
) -> Book:
    book = await _book(session, book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)
    book.title = title
    await session.commit()
    return book


async def delete_book(session: AsyncSession, user: Principal, book_id: uuid.UUID) -> None:
    book = await _book(session, book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)
    await session.execute(delete(Book).where(Book.id == book_id))
    await session.commit()


# ---------------- Sections (sub-headings inside a book) ----------------


async def create_section(
    session: AsyncSession, user: Principal, *, book_id: uuid.UUID, title: str
) -> Section:
    book = await _book(session, book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)
    existing = {
        s
        for (s,) in (
            await session.execute(select(Section.slug).where(Section.book_id == book_id))
        ).all()
    }
    orders = list(
        (await session.execute(select(Section.sort_order).where(Section.book_id == book_id)))
        .scalars()
    )
    section = Section(
        book_id=book_id,
        slug=slugify(title, existing),
        title=title,
        sort_order=(max(orders) + 1) if orders else 0,
    )
    session.add(section)
    await session.commit()
    return section


async def update_section(
    session: AsyncSession, user: Principal, section_id: uuid.UUID, *, title: str
) -> Section:
    section = await _section(session, section_id)
    book = await _book(session, section.book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)
    section.title = title
    await session.commit()
    return section


async def delete_section(
    session: AsyncSession, user: Principal, section_id: uuid.UUID
) -> None:
    """Delete a section, ungrouping its pages (their content is kept)."""
    section = await _section(session, section_id)
    book = await _book(session, section.book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)
    pages = list(
        (
            await session.execute(select(Page).where(Page.section_id == section_id))
        ).scalars()
    )
    for p in pages:
        p.section_id = None
    await session.flush()
    await session.execute(delete(Section).where(Section.id == section_id))
    await session.commit()


async def update_page(
    session: AsyncSession,
    user: Principal,
    page_id: uuid.UUID,
    *,
    title: str | None = None,
    slug: str | None = None,
    locale: str = "en",
) -> dict[str, Any]:
    """Rename a page: update the translation title (for ``locale``) and/or slug."""
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    if slug:
        page.slug = slugify(slug)
    if title is not None:
        tr = await _translation(session, page_id, locale)
        if tr is not None:
            tr.title = title
    await session.commit()
    return {"id": page.id, "slug": page.slug}


async def create_page(
    session: AsyncSession,
    user: Principal,
    *,
    book_id: uuid.UUID,
    slug: str,
    title: str,
    locale: str = "en",
    parent_page_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    markdown: str = "",
    sort_order: int = 0,
) -> Page:
    book = await _book(session, book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)
    page = Page(
        book_id=book_id,
        slug=slug,
        parent_page_id=parent_page_id,
        section_id=section_id,
        sort_order=sort_order,
        status="draft",
    )
    session.add(page)
    await session.flush()
    tr = PageTranslation(page_id=page.id, locale=locale, title=title, markdown=markdown, revision=1)
    session.add(tr)
    await session.flush()
    session.add(
        PageRevision(
            page_translation_id=tr.id, revision=1, markdown=markdown, author_id=_as_uuid(user.sub)
        )
    )
    await session.commit()
    return page


_MAX_PDF_BYTES = 25 * 1024 * 1024


async def import_pdf_document(
    session: AsyncSession,
    user: Principal,
    *,
    book_id: uuid.UUID,
    data: bytes,
    filename: str = "document.pdf",
    locale: str = "en",
    parent_page_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Import a PDF as one or more *draft* pages under ``book_id`` (F7).

    Each top-level bookmark becomes a page (single page when there is no outline);
    embedded images become media assets referenced inline. Imported pages are
    drafts — the author reviews, edits, and publishes (which indexes for search).
    """
    book = await _book(session, book_id)
    space = await _space(session, book.space_id)
    _require(user, space.slug, Permission.WRITE)

    parsed = await _parse_pdf_or_422(data, filename)
    created = await _import_sections(
        session,
        book=book,
        space=space,
        parsed=parsed,
        locale=locale,
        parent_page_id=parent_page_id,
        author=_as_uuid(user.sub),
    )
    await session.commit()
    return created


async def import_pdf_as_book(
    session: AsyncSession,
    user: Principal,
    *,
    space_slug: str,
    data: bytes,
    filename: str = "document.pdf",
    locale: str = "en",
) -> dict[str, Any]:
    """Create a new *book* from a PDF: the file's sections become draft pages (F7).

    The book is titled from the filename. Pages are drafts — review and publish.
    """
    space = await _space_by_slug(session, space_slug)
    _require(user, space.slug, Permission.WRITE)
    parsed = await _parse_pdf_or_422(data, filename)
    title = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE).strip() or "Imported book"
    book = await _new_book(session, space, title)
    created = await _import_sections(
        session,
        book=book,
        space=space,
        parsed=parsed,
        locale=locale,
        parent_page_id=None,
        author=_as_uuid(user.sub),
    )
    await session.commit()
    return {"book": {"id": book.id, "slug": book.slug, "title": book.title}, "pages": created}


async def import_pdf_as_markdown(
    session: AsyncSession,
    user: Principal,
    *,
    space_slug: str,
    data: bytes,
    filename: str = "document.pdf",
) -> dict[str, Any]:
    """Parse a PDF and return its content as a single Markdown string (F7).

    Unlike :func:`import_pdf_document`, this creates no pages — it is used to drop
    a PDF's text and images straight into the page the author is editing. Embedded
    images are persisted as media assets in ``space_slug`` and referenced inline.
    """
    space = await _space_by_slug(session, space_slug)
    _require(user, space.slug, Permission.WRITE)
    parsed = await _parse_pdf_or_422(data, filename)
    base = get_settings().api_public_url.rstrip("/")
    author = _as_uuid(user.sub)

    parts: list[str] = []
    for section in parsed.sections:
        markdown = section.markdown
        for i, img in enumerate(section.images):
            asset = MediaAsset(
                space_id=space.id,
                filename=img.name,
                content_type=img.content_type,
                size=len(img.data),
                content=img.data,
                uploaded_by=author,
            )
            session.add(asset)
            await session.flush()
            url = f"{base}/api/v1/media/{asset.id}" if base else f"/api/v1/media/{asset.id}"
            markdown = markdown.replace(f"{{{{XDOCS_IMAGE_{i}}}}}", f"![{img.name}]({url})")
        markdown = _strip_image_placeholders(markdown)
        if markdown.strip():
            parts.append(markdown)
    await session.commit()
    return {"title": parsed.title, "markdown": "\n\n".join(parts).strip()}


async def _parse_pdf_or_422(data: bytes, filename: str) -> Any:
    if not data[:5].startswith(b"%PDF"):
        raise ValidationError("Not a PDF file.", details={"filename": filename})
    if len(data) > _MAX_PDF_BYTES:
        raise ValidationError("PDF exceeds the size limit.", details={"max": _MAX_PDF_BYTES})
    try:
        parsed = await run_in_threadpool(parse_pdf, data, filename)
    except Exception as exc:  # noqa: BLE001 - surface any parse failure as a 422
        raise ValidationError("Could not parse PDF.", details={"reason": str(exc)}) from exc
    if not parsed.sections:
        raise ValidationError("No extractable content in the PDF.")
    return parsed


async def _import_sections(
    session: AsyncSession,
    *,
    book: Book,
    space: Space,
    parsed: Any,
    locale: str,
    parent_page_id: uuid.UUID | None,
    author: uuid.UUID | None,
) -> list[dict[str, Any]]:
    """Turn a parsed PDF's sections into draft pages under ``book``."""
    base = get_settings().api_public_url.rstrip("/")

    existing = {
        s
        for (s,) in (
            await session.execute(
                select(Page.slug).where(
                    Page.book_id == book.id, Page.parent_page_id == parent_page_id
                )
            )
        ).all()
    }
    start_order = await _next_sort_order(session, book.id, parent_page_id)

    created: list[dict[str, Any]] = []
    for offset, section in enumerate(parsed.sections):
        markdown = section.markdown
        for i, img in enumerate(section.images):
            asset = MediaAsset(
                space_id=space.id,
                filename=img.name,
                content_type=img.content_type,
                size=len(img.data),
                content=img.data,
                uploaded_by=author,
            )
            session.add(asset)
            await session.flush()
            url = f"{base}/api/v1/media/{asset.id}" if base else f"/api/v1/media/{asset.id}"
            markdown = markdown.replace(f"{{{{XDOCS_IMAGE_{i}}}}}", f"![{img.name}]({url})")
        markdown = _strip_image_placeholders(markdown)  # drop any undecoded leftovers

        slug = slugify(section.title, existing)
        page = Page(
            book_id=book.id,
            slug=slug,
            parent_page_id=parent_page_id,
            sort_order=start_order + offset,
            status="draft",
        )
        session.add(page)
        await session.flush()
        tr = PageTranslation(
            page_id=page.id, locale=locale, title=section.title, markdown=markdown, revision=1
        )
        session.add(tr)
        await session.flush()
        session.add(
            PageRevision(page_translation_id=tr.id, revision=1, markdown=markdown, author_id=author)
        )
        created.append({"id": page.id, "slug": slug, "title": section.title})
    return created


async def _next_sort_order(
    session: AsyncSession, book_id: uuid.UUID, parent_page_id: uuid.UUID | None
) -> int:
    rows = list(
        (
            await session.execute(
                select(Page.sort_order).where(
                    Page.book_id == book_id, Page.parent_page_id == parent_page_id
                )
            )
        ).scalars()
    )
    return (max(rows) + 1) if rows else 0


def _strip_image_placeholders(markdown: str) -> str:
    return re.sub(r"\n*\{\{XDOCS_IMAGE_\d+\}\}\n*", "\n\n", markdown).strip()


async def delete_page(session: AsyncSession, user: Principal, page_id: uuid.UUID) -> None:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    await session.execute(delete(Page).where(Page.id == page_id))
    await session.commit()


async def reorder_pages(
    session: AsyncSession, user: Principal, items: list[dict[str, Any]]
) -> None:
    for it in items:
        page = await _page(session, uuid.UUID(it["id"]))
        space = await _space_of_page(session, page)
        _require(user, space.slug, Permission.WRITE)
        page.sort_order = int(it["sort_order"])
        if "parent_id" in it:
            page.parent_page_id = uuid.UUID(it["parent_id"]) if it["parent_id"] else None
    await session.commit()


# ---------------- Content editing ----------------


async def _translation(
    session: AsyncSession, page_id: uuid.UUID, locale: str
) -> PageTranslation | None:
    return (
        await session.execute(
            select(PageTranslation).where(
                PageTranslation.page_id == page_id, PageTranslation.locale == locale
            )
        )
    ).scalar_one_or_none()


async def save_translation(
    session: AsyncSession,
    user: Principal,
    *,
    page_id: uuid.UUID,
    locale: str,
    markdown: str,
    base_revision: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)

    tr = await _translation(session, page_id, locale)
    if tr is None:
        tr = PageTranslation(
            page_id=page_id, locale=locale, title=title or "Untitled", markdown=markdown, revision=1
        )
        session.add(tr)
        await session.flush()
        new_rev = 1
    else:
        if base_revision is not None and tr.revision != base_revision:
            raise RevisionConflictError(
                "This page was modified since you loaded it.",
                details={"current": tr.revision, "base": base_revision},
            )
        # On the first edit of a translation that has no history yet (e.g. seeded
        # content), snapshot the pre-edit baseline so history is complete.
        has_history = (
            await session.execute(
                select(PageRevision.id).where(PageRevision.page_translation_id == tr.id).limit(1)
            )
        ).first()
        if not has_history:
            session.add(
                PageRevision(page_translation_id=tr.id, revision=tr.revision, markdown=tr.markdown)
            )
        tr.markdown = markdown
        if title is not None:
            tr.title = title
        tr.revision += 1
        new_rev = tr.revision

    session.add(
        PageRevision(
            page_translation_id=tr.id,
            revision=new_rev,
            markdown=markdown,
            author_id=_as_uuid(user.sub),
        )
    )
    await session.commit()
    return {"page_id": page_id, "locale": locale, "revision": new_rev, "status": page.status}


async def publish_page(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, *, locale: str | None = None
) -> dict[str, Any]:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)

    translations = list(
        (
            await session.execute(select(PageTranslation).where(PageTranslation.page_id == page_id))
        ).scalars()
    )
    for tr in translations:
        if locale and tr.locale != locale:
            continue
        html, headings = render_markdown(tr.markdown)
        tr.html_cached = html
        tr.headings = headings
        # The current draft becomes the published snapshot (replaces the live
        # version); after this markdown == published_markdown, so no pending draft.
        tr.published_markdown = tr.markdown
        tr.published_revision = tr.revision
        tr.published_at = datetime.now(UTC)
    page.status = "published"
    await session.flush()
    chunks = await reindex_page(session, page_id)
    await session.commit()
    return {"page_id": page_id, "status": "published", "indexed_chunks": chunks}


async def discard_draft(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, locale: str
) -> dict[str, Any]:
    """Revert the working draft back to the published snapshot (drop edits)."""
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    tr = await _translation(session, page_id, locale)
    if tr is None:
        raise NotFoundError("Translation not found.")
    if tr.published_markdown is None:
        raise ValidationError("This page has no published version to revert to.")
    if tr.markdown != tr.published_markdown:
        tr.markdown = tr.published_markdown
        tr.revision += 1
        session.add(
            PageRevision(
                page_translation_id=tr.id,
                revision=tr.revision,
                markdown=tr.markdown,
                author_id=_as_uuid(user.sub),
            )
        )
    await session.commit()
    return {"page_id": page_id, "locale": locale, "revision": tr.revision}


async def unpublish_page(
    session: AsyncSession, user: Principal, page_id: uuid.UUID
) -> dict[str, Any]:
    """Revert a page to draft so it disappears from the reader and the search
    index, while keeping its content/revisions intact (F3)."""
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    page.status = "draft"
    await session.flush()
    # reindex_page deletes the page's chunks and adds none (it skips drafts).
    await reindex_page(session, page_id)
    await session.commit()
    return {"page_id": page_id, "status": "draft"}


async def get_revision(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, locale: str, revision: int
) -> dict[str, Any]:
    """Return a single revision's markdown so the editor can preview/diff it."""
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    tr = await _translation(session, page_id, locale)
    if tr is None:
        raise NotFoundError("Translation not found.")
    rev = (
        await session.execute(
            select(PageRevision).where(
                PageRevision.page_translation_id == tr.id, PageRevision.revision == revision
            )
        )
    ).scalar_one_or_none()
    if rev is None:
        raise NotFoundError("Revision not found.", details={"revision": revision})
    return {"revision": rev.revision, "markdown": rev.markdown, "created_at": rev.created_at}


async def list_revisions(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, locale: str
) -> list[dict[str, Any]]:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    tr = await _translation(session, page_id, locale)
    if tr is None:
        return []
    rows = list(
        (
            await session.execute(
                select(PageRevision)
                .where(PageRevision.page_translation_id == tr.id)
                .order_by(PageRevision.revision.desc())
            )
        ).scalars()
    )
    return [
        {"revision": r.revision, "author_id": r.author_id, "created_at": r.created_at} for r in rows
    ]


async def restore_revision(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, locale: str, revision: int
) -> dict[str, Any]:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    tr = await _translation(session, page_id, locale)
    if tr is None:
        raise NotFoundError("Translation not found.")
    target = (
        await session.execute(
            select(PageRevision).where(
                PageRevision.page_translation_id == tr.id, PageRevision.revision == revision
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise NotFoundError("Revision not found.", details={"revision": revision})
    return await save_translation(
        session,
        user,
        page_id=page_id,
        locale=locale,
        markdown=target.markdown,
        base_revision=tr.revision,
    )


# ---------------- Product versions (G1/G2) ----------------


async def _version(session: AsyncSession, version_id: uuid.UUID) -> ProductVersion:
    v = (
        await session.execute(select(ProductVersion).where(ProductVersion.id == version_id))
    ).scalar_one_or_none()
    if v is None:
        raise NotFoundError("Version not found.", details={"version": str(version_id)})
    return v


async def create_version(
    session: AsyncSession,
    user: Principal,
    *,
    space_id: uuid.UUID,
    label: str,
    visibility: str = "internal",
    sort_order: int = 0,
) -> ProductVersion:
    space = await _space(session, space_id)
    _require(user, space.slug, Permission.WRITE)
    v = ProductVersion(
        space_id=space_id,
        label=label,
        visibility=visibility,
        is_default=False,
        sort_order=sort_order,
    )
    session.add(v)
    await session.commit()
    return v


async def update_version(
    session: AsyncSession,
    user: Principal,
    version_id: uuid.UUID,
    *,
    visibility: str | None = None,
    is_default: bool | None = None,
) -> ProductVersion:
    v = await _version(session, version_id)
    space = await _space(session, v.space_id)
    _require(user, space.slug, Permission.WRITE)
    if visibility is not None:
        v.visibility = visibility
    if is_default:
        # Only one default per space.
        others = list(
            (
                await session.execute(
                    select(ProductVersion).where(ProductVersion.space_id == v.space_id)
                )
            ).scalars()
        )
        for o in others:
            o.is_default = False
        v.is_default = True
        v.visibility = "published"  # a default must be visible
    await session.commit()
    return v


async def clone_version(
    session: AsyncSession, user: Principal, version_id: uuid.UUID, *, new_label: str
) -> ProductVersion:
    src = await _version(session, version_id)
    space = await _space(session, src.space_id)
    _require(user, space.slug, Permission.WRITE)
    new = ProductVersion(
        space_id=src.space_id,
        label=new_label,
        visibility="internal",
        is_default=False,
        sort_order=src.sort_order + 1,
    )
    session.add(new)
    await session.flush()

    books = list((await session.execute(select(Book).where(Book.version_id == src.id))).scalars())
    for b in books:
        nb = Book(
            space_id=b.space_id,
            version_id=new.id,
            slug=b.slug,
            title=b.title,
            sort_order=b.sort_order,
        )
        session.add(nb)
        await session.flush()
        pages = list(
            (
                await session.execute(
                    select(Page).where(Page.book_id == b.id).order_by(Page.sort_order)
                )
            ).scalars()
        )
        id_map: dict[uuid.UUID, uuid.UUID] = {}
        for p in pages:
            np = Page(book_id=nb.id, slug=p.slug, sort_order=p.sort_order, status=p.status)
            session.add(np)
            await session.flush()
            id_map[p.id] = np.id
            trs = list(
                (
                    await session.execute(
                        select(PageTranslation).where(PageTranslation.page_id == p.id)
                    )
                ).scalars()
            )
            for t in trs:
                session.add(
                    PageTranslation(
                        page_id=np.id,
                        locale=t.locale,
                        title=t.title,
                        markdown=t.markdown,
                        html_cached=t.html_cached,
                        headings=t.headings,
                        translation_status=t.translation_status,
                        revision=t.revision,
                        published_at=t.published_at,
                    )
                )
        # Re-link parent relationships within the cloned book.
        for p in pages:
            if p.parent_page_id and p.id in id_map and p.parent_page_id in id_map:
                np = await _page(session, id_map[p.id])
                np.parent_page_id = id_map[p.parent_page_id]
    await session.commit()
    return new


# ---------------- LLM-assisted translation (G4) ----------------


async def generate_translation_draft(
    session: AsyncSession,
    user: Principal,
    *,
    page_id: uuid.UUID,
    locale: str,
    source_locale: str = "en",
) -> dict[str, Any]:
    from app.llm.chat import get_chat_provider

    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    src = await _translation(session, page_id, source_locale)
    if src is None:
        src = (
            (
                await session.execute(
                    select(PageTranslation).where(PageTranslation.page_id == page_id)
                )
            )
            .scalars()
            .first()
        )
    if src is None:
        raise NotFoundError("No source translation to translate from.")

    translated = await get_chat_provider().complete(
        f"Translate the following Markdown to {locale}. Preserve formatting.", src.markdown
    )
    tr = await _translation(session, page_id, locale)
    if tr is None:
        tr = PageTranslation(
            page_id=page_id,
            locale=locale,
            title=src.title,
            markdown=translated,
            revision=1,
            translation_status="llm_draft",
        )
        session.add(tr)
        await session.flush()
        new_rev = 1
    else:
        tr.markdown = translated
        tr.translation_status = "llm_draft"
        tr.revision += 1
        new_rev = tr.revision
    session.add(
        PageRevision(
            page_translation_id=tr.id,
            revision=new_rev,
            markdown=translated,
            author_id=_as_uuid(user.sub),
        )
    )
    await session.commit()
    return {
        "page_id": page_id,
        "locale": locale,
        "revision": new_rev,
        "translation_status": "llm_draft",
    }


async def approve_translation(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, locale: str
) -> dict[str, Any]:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    tr = await _translation(session, page_id, locale)
    if tr is None:
        raise NotFoundError("Translation not found.")
    tr.translation_status = "approved"
    await session.commit()
    return {"page_id": page_id, "locale": locale, "translation_status": "approved"}


# ---------------- Admin tree (includes drafts) ----------------


async def admin_tree(session: AsyncSession, user: Principal, slug: str) -> dict[str, Any]:
    space = (await session.execute(select(Space).where(Space.slug == slug))).scalar_one_or_none()
    if space is None:
        raise NotFoundError("Space not found.", details={"space": slug})
    _require(user, slug, Permission.WRITE)
    books = list(
        (
            await session.execute(
                select(Book).where(Book.space_id == space.id).order_by(Book.sort_order)
            )
        ).scalars()
    )
    out_books = []
    for b in books:
        sections = list(
            (
                await session.execute(
                    select(Section).where(Section.book_id == b.id).order_by(Section.sort_order)
                )
            ).scalars()
        )
        pages = list(
            (
                await session.execute(
                    select(Page).where(Page.book_id == b.id).order_by(Page.sort_order)
                )
            ).scalars()
        )
        titles: dict[uuid.UUID, str] = {}
        drafted: set[uuid.UUID] = set()  # published pages with unpublished edits
        if pages:
            trs = (
                await session.execute(
                    select(PageTranslation).where(
                        PageTranslation.page_id.in_([p.id for p in pages])
                    )
                )
            ).scalars()
            for t in trs:
                titles.setdefault(t.page_id, t.title)
                if t.published_markdown is not None and t.markdown != t.published_markdown:
                    drafted.add(t.page_id)

        def page_node(
            p: Page,
            titles: dict[uuid.UUID, str] = titles,
            drafted: set[uuid.UUID] = drafted,
        ) -> dict[str, Any]:
            return {
                "id": p.id,
                "slug": p.slug,
                "title": titles.get(p.id, p.slug),
                "status": p.status,
                # A published page with edits not yet re-published shows a second
                # "Draft" row in the sidebar (Published stays live for readers).
                "has_draft": p.status == "published" and p.id in drafted,
                "parent_page_id": p.parent_page_id,
                "section_id": p.section_id,
            }

        out_books.append(
            {
                "id": b.id,
                "slug": b.slug,
                "title": b.title,
                "version_id": b.version_id,
                "sections": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "slug": s.slug,
                        "pages": [page_node(p) for p in pages if p.section_id == s.id],
                    }
                    for s in sections
                ],
                "pages": [page_node(p) for p in pages if p.section_id is None],
            }
        )
    return {
        "space": space.slug,
        "title": space.title,
        "color": space.color,
        "books": out_books,
    }


async def get_translation(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, locale: str
) -> dict[str, Any]:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    tr = await _translation(session, page_id, locale)
    if tr is None:
        raise NotFoundError("Translation not found.")
    has_draft = (
        page.status == "published"
        and tr.published_markdown is not None
        and tr.markdown != tr.published_markdown
    )
    return {
        "page_id": page_id,
        "locale": tr.locale,
        "title": tr.title,
        "markdown": tr.markdown,
        "published_markdown": tr.published_markdown,
        "has_draft": has_draft,
        "revision": tr.revision,
        "status": page.status,
        "translation_status": tr.translation_status,
    }
