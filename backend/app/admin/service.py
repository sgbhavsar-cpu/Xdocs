"""Authoring service (F2–F4, F6): structure CRUD, draft/publish, revisions.

All mutations are permission-checked: WRITE to author within a space, ADMIN to
create/delete spaces. Publishing renders cached HTML + headings and re-indexes
the page for search.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, Principal
from app.content.render import render_markdown
from app.core.errors import ForbiddenError, NotFoundError, RevisionConflictError
from app.models.content import Book, Page, PageRevision, PageTranslation, ProductVersion, Space
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


async def _space_of_page(session: AsyncSession, page: Page) -> Space:
    book = await _book(session, page.book_id)
    return await _space(session, book.space_id)


# ---------------- Spaces / Books / Pages ----------------


async def create_space(
    session: AsyncSession, user: Principal, *, slug: str, title: str, default_locale: str = "en"
) -> Space:
    _require_global_admin(user)
    space = Space(slug=slug, title=title, default_locale=default_locale)
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


async def create_page(
    session: AsyncSession,
    user: Principal,
    *,
    book_id: uuid.UUID,
    slug: str,
    title: str,
    locale: str = "en",
    parent_page_id: uuid.UUID | None = None,
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
        tr.published_at = datetime.now(UTC)
    page.status = "published"
    await session.flush()
    chunks = await reindex_page(session, page_id)
    await session.commit()
    return {"page_id": page_id, "status": "published", "indexed_chunks": chunks}


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
        pages = list(
            (
                await session.execute(
                    select(Page).where(Page.book_id == b.id).order_by(Page.sort_order)
                )
            ).scalars()
        )
        titles: dict[uuid.UUID, str] = {}
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
        out_books.append(
            {
                "id": b.id,
                "slug": b.slug,
                "title": b.title,
                "version_id": b.version_id,
                "pages": [
                    {
                        "id": p.id,
                        "slug": p.slug,
                        "title": titles.get(p.id, p.slug),
                        "status": p.status,
                        "parent_page_id": p.parent_page_id,
                    }
                    for p in pages
                ],
            }
        )
    return {"space": space.slug, "books": out_books}


async def get_translation(
    session: AsyncSession, user: Principal, page_id: uuid.UUID, locale: str
) -> dict[str, Any]:
    page = await _page(session, page_id)
    space = await _space_of_page(session, page)
    _require(user, space.slug, Permission.WRITE)
    tr = await _translation(session, page_id, locale)
    if tr is None:
        raise NotFoundError("Translation not found.")
    return {
        "page_id": page_id,
        "locale": tr.locale,
        "title": tr.title,
        "markdown": tr.markdown,
        "revision": tr.revision,
        "status": page.status,
        "translation_status": tr.translation_status,
    }
