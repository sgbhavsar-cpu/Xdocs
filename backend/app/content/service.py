"""Content read service: spaces, navigation tree, and page resolution (B2).

All functions are ACL-aware: callers pass the authenticated Principal and results
are limited to spaces the caller can read. Versions with `internal` visibility are
hidden from readers (design §16.5). Queries are explicit (no async lazy-loading).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, Principal
from app.content.render import render_markdown
from app.core.errors import ForbiddenError, NotFoundError
from app.models.content import Book, Page, PageTranslation, ProductVersion, Section, Space


def _version_ref(v: ProductVersion) -> dict[str, Any]:
    return {"id": v.id, "label": v.label}


async def _published_versions(session: AsyncSession, space_id: uuid.UUID) -> list[ProductVersion]:
    rows = await session.execute(
        select(ProductVersion)
        .where(ProductVersion.space_id == space_id, ProductVersion.visibility == "published")
        .order_by(ProductVersion.sort_order)
    )
    return list(rows.scalars())


async def list_spaces(session: AsyncSession, user: Principal) -> list[dict[str, Any]]:
    spaces = (await session.execute(select(Space).order_by(Space.slug))).scalars()
    out: list[dict[str, Any]] = []
    for space in spaces:
        if not user.can(space.slug, Permission.READ):
            continue
        versions = await _published_versions(session, space.id)
        default = next((v for v in versions if v.is_default), versions[0] if versions else None)
        out.append(
            {
                "id": space.id,
                "slug": space.slug,
                "title": space.title,
                "description": space.description,
                "color": space.color,
                "default_locale": space.default_locale,
                "default_version": _version_ref(default) if default else None,
                "visible_versions": [_version_ref(v) for v in versions],
            }
        )
    return out


async def _resolve_space(session: AsyncSession, slug: str, user: Principal) -> Space:
    space = (await session.execute(select(Space).where(Space.slug == slug))).scalar_one_or_none()
    if space is None:
        raise NotFoundError("Space not found.", details={"space": slug})
    if not user.can(slug, Permission.READ):
        raise ForbiddenError("No read access to this space.", details={"space": slug})
    return space


async def _resolve_version(
    session: AsyncSession, space: Space, label: str | None
) -> ProductVersion:
    versions = await _published_versions(session, space.id)
    if not versions:
        raise NotFoundError("No published version for this space.", details={"space": space.slug})
    if label:
        match = next((v for v in versions if v.label == label), None)
        if match is None:
            raise NotFoundError("Version not found or not published.", details={"version": label})
        return match
    return next((v for v in versions if v.is_default), versions[0])


async def get_tree(
    session: AsyncSession,
    slug: str,
    user: Principal,
    *,
    version_label: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    space = await _resolve_space(session, slug, user)
    version = await _resolve_version(session, space, version_label)
    loc = locale or space.default_locale

    books = list(
        (
            await session.execute(
                select(Book).where(Book.version_id == version.id).order_by(Book.sort_order)
            )
        ).scalars()
    )
    book_ids = [b.id for b in books]

    pages: list[Page] = []
    titles: dict[uuid.UUID, str] = {}
    locales_present: set[str] = set()
    if book_ids:
        pages = list(
            (
                await session.execute(
                    select(Page)
                    .where(Page.book_id.in_(book_ids), Page.status == "published")
                    .order_by(Page.sort_order)
                )
            ).scalars()
        )
        page_ids = [p.id for p in pages]
        # Titles come from the requested locale, falling back to the space default.
        trans = (
            await session.execute(
                select(PageTranslation).where(PageTranslation.page_id.in_(page_ids))
            )
        ).scalars()
        by_page: dict[uuid.UUID, dict[str, str]] = {}
        for t in trans:
            by_page.setdefault(t.page_id, {})[t.locale] = t.title
            locales_present.add(t.locale)
        for pid, locales in by_page.items():
            titles[pid] = (
                locales.get(loc)
                or locales.get(space.default_locale)
                or next(iter(locales.values()))
            )

    # Sections (sub-headings) declared in the visible books.
    sections_by_book: dict[uuid.UUID, list[Section]] = {}
    if book_ids:
        section_rows = (
            await session.execute(
                select(Section).where(Section.book_id.in_(book_ids)).order_by(Section.sort_order)
            )
        ).scalars()
        for s in section_rows:
            sections_by_book.setdefault(s.book_id, []).append(s)

    # Build the page tree per book. Children (nested pages) ignore sections; only
    # top-level pages are grouped under a section header.
    def build_children(book_id: uuid.UUID, parent: uuid.UUID | None) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for p in pages:
            if p.book_id == book_id and p.parent_page_id == parent:
                children = build_children(book_id, p.id)
                nodes.append(
                    {
                        "id": p.id,
                        "slug": p.slug,
                        "title": titles.get(p.id, p.slug),
                        "has_children": bool(children),
                        "children": children,
                    }
                )
        return nodes

    def build_roots(book_id: uuid.UUID, section_id: uuid.UUID | None) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for p in pages:
            if (
                p.book_id == book_id
                and p.parent_page_id is None
                and p.section_id == section_id
            ):
                children = build_children(book_id, p.id)
                nodes.append(
                    {
                        "id": p.id,
                        "slug": p.slug,
                        "title": titles.get(p.id, p.slug),
                        "has_children": bool(children),
                        "children": children,
                    }
                )
        return nodes

    def book_node(b: Book) -> dict[str, Any]:
        section_nodes = []
        for s in sections_by_book.get(b.id, []):
            sp = build_roots(b.id, s.id)
            if sp:  # hide empty section headers from readers
                section_nodes.append({"id": s.id, "title": s.title, "pages": sp})
        return {
            "id": b.id,
            "slug": b.slug,
            "title": b.title,
            "sections": section_nodes,
            "pages": build_roots(b.id, None),
        }

    return {
        "space": space.slug,
        "version": _version_ref(version),
        "locale": loc,
        "locales": sorted(locales_present or {space.default_locale}),
        "books": [book_node(b) for b in books],
    }


async def get_page(
    session: AsyncSession,
    page_id: uuid.UUID,
    user: Principal,
    *,
    locale: str | None = None,
) -> dict[str, Any]:
    page = (await session.execute(select(Page).where(Page.id == page_id))).scalar_one_or_none()
    if page is None or page.status != "published":
        raise NotFoundError("Page not found.", details={"page": str(page_id)})

    book = (await session.execute(select(Book).where(Book.id == page.book_id))).scalar_one()
    space = (await session.execute(select(Space).where(Space.id == book.space_id))).scalar_one()
    if not user.can(space.slug, Permission.READ):
        raise ForbiddenError("No read access to this space.", details={"space": space.slug})
    version = (
        await session.execute(select(ProductVersion).where(ProductVersion.id == book.version_id))
    ).scalar_one()

    translations = list(
        (
            await session.execute(select(PageTranslation).where(PageTranslation.page_id == page_id))
        ).scalars()
    )
    if not translations:
        raise NotFoundError("Page has no content.", details={"page": str(page_id)})

    available = sorted(t.locale for t in translations)
    requested = locale or space.default_locale
    by_locale = {t.locale: t for t in translations}

    fallback = None
    chosen = by_locale.get(requested)
    if chosen is None:
        # Missing-locale policy (design §16.3): serve default + offer auto-translate.
        served = space.default_locale if space.default_locale in by_locale else available[0]
        chosen = by_locale[served]
        fallback = {
            "served_locale": served,
            "requested_locale": requested,
            "can_auto_translate": True,
        }

    if chosen.html_cached:
        html, headings = chosen.html_cached, (chosen.headings or [])
    else:
        html, headings = render_markdown(chosen.markdown)

    etag = f'W/"{page.id}.{chosen.locale}.{chosen.revision}"'
    return {
        "id": page.id,
        "slug": page.slug,
        "title": chosen.title,
        "space": space.slug,
        "book": book.slug,
        "version": _version_ref(version),
        "locale": chosen.locale,
        "translation_status": chosen.translation_status,
        "html": html,
        "headings": headings,
        "available_locales": available,
        "fallback": fallback,
        "etag": etag,
    }
