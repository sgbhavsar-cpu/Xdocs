"""Analytics: record page views & LLM feedback; aggregate dashboards (H1, design §10)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, Principal
from app.core.errors import ForbiddenError, NotFoundError
from app.models.content import Book, Page, PageTranslation, Space
from app.models.llm import AnalyticsEvent


async def _readable_spaces(session: AsyncSession, user: Principal) -> set[str]:
    slugs = list((await session.execute(select(Space.slug))).scalars())
    return {s for s in slugs if user.can(s, Permission.READ)}


def _require_any_write(user: Principal) -> None:
    has_write = (user.global_permission or Permission.READ) >= Permission.WRITE or any(
        p >= Permission.WRITE for p in user.space_permissions.values()
    )
    if not has_write:
        raise ForbiddenError("Editor permission required.")


async def record_pageview(session: AsyncSession, user: Principal, page_id: uuid.UUID) -> None:
    page = (await session.execute(select(Page).where(Page.id == page_id))).scalar_one_or_none()
    if page is None:
        raise NotFoundError("Page not found.", details={"page": str(page_id)})
    book = (await session.execute(select(Book).where(Book.id == page.book_id))).scalar_one()
    space = (await session.execute(select(Space).where(Space.id == book.space_id))).scalar_one()
    if not user.can(space.slug, Permission.READ):
        raise ForbiddenError("No read access.", details={"space": space.slug})
    session.add(AnalyticsEvent(type="page_view", subject_id=page_id, data={"space": space.slug}))
    await session.commit()


async def popular_pages(
    session: AsyncSession, user: Principal, *, space: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    _require_any_write(user)
    allowed = await _readable_spaces(session, user)
    rows = (
        await session.execute(
            select(AnalyticsEvent.subject_id, func.count().label("views"))
            .where(AnalyticsEvent.type == "page_view")
            .group_by(AnalyticsEvent.subject_id)
        )
    ).all()
    counts = {pid: views for pid, views in rows if pid is not None}
    if not counts:
        return []

    pages = list(
        (await session.execute(select(Page).where(Page.id.in_(list(counts.keys()))))).scalars()
    )
    books = {b.id: b for b in (await session.execute(select(Book))).scalars()}
    spaces = {s.id: s for s in (await session.execute(select(Space))).scalars()}
    titles: dict[uuid.UUID, str] = {}
    trs = (
        await session.execute(
            select(PageTranslation).where(PageTranslation.page_id.in_([p.id for p in pages]))
        )
    ).scalars()
    for t in trs:
        titles.setdefault(t.page_id, t.title)

    out = []
    for p in pages:
        book = books.get(p.book_id)
        space_obj = spaces.get(book.space_id) if book else None
        if space_obj is None or space_obj.slug not in allowed:
            continue
        if space and space_obj.slug != space:
            continue
        out.append(
            {
                "page_id": p.id,
                "title": titles.get(p.id, p.slug),
                "space": space_obj.slug,
                "views": counts[p.id],
            }
        )
    out.sort(key=lambda x: x["views"], reverse=True)
    return out[:limit]


async def feedback_summary(session: AsyncSession, user: Principal) -> dict[str, Any]:
    _require_any_write(user)
    events = list(
        (
            await session.execute(
                select(AnalyticsEvent).where(AnalyticsEvent.type == "llm_feedback")
            )
        ).scalars()
    )
    up = sum(1 for e in events if (e.data or {}).get("rating") == "up")
    down = sum(1 for e in events if (e.data or {}).get("rating") == "down")
    comments = [
        {"rating": (e.data or {}).get("rating"), "comment": (e.data or {}).get("comment")}
        for e in events
        if (e.data or {}).get("comment")
    ]
    return {"up": up, "down": down, "total": len(events), "comments": comments[:20]}
