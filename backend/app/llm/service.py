"""RAG Ask, summarize, extract, translate, and feedback (D2, D4, D5, D6).

Retrieval is ACL/scope-aware (reuses the search scorer). Answers are grounded in
retrieved context with citations back to page/section; when nothing is retrieved
the model returns a "not covered" answer with no citations.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, Principal
from app.content.render import render_markdown
from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError
from app.llm.chat import estimate_tokens, get_chat_provider
from app.llm.guard import LlmGuard
from app.models.content import Book, Page, PageTranslation, Space
from app.models.llm import AnalyticsEvent, LlmArtifact, TranslationCache
from app.search.service import retrieve

ASK_SYSTEM = (
    "You are a documentation assistant. Answer the question using ONLY the provided "
    "context. If the answer is not in the context, say you could not find it in the "
    "documentation. Cite sources by their bracketed number."
)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _is_expired(expires_at: datetime) -> bool:
    """Tz-safe expiry check (SQLite returns naive datetimes; Postgres aware)."""
    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at < now


def _build_context(chunks: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    lines: list[str] = []
    citations: list[dict[str, Any]] = []
    for i, ch in enumerate(chunks, start=1):
        lines.append(f"[{i}] {ch.content}")
        anchor = (ch.anchor or {}).get("heading_id") if ch.anchor else None
        citations.append({"page_id": str(ch.page_id), "anchor": anchor, "title": ch.page_title})
    return "\n\n".join(lines), citations


async def ask_stream(
    session: AsyncSession,
    user: Principal,
    guard: LlmGuard,
    *,
    question: str,
    scope: str = "corpus",
    locale: str | None = None,
) -> AsyncIterator[str]:
    answer_id = str(uuid.uuid4())
    chunks = await retrieve(session, user, q=question, scope=scope, locale=locale, k=5)

    if not chunks:
        yield _sse("token", {"text": "I couldn't find this in the documentation."})
        yield _sse("citations", {"items": []})
        yield _sse("done", {"answer_id": answer_id, "tokens": {"in": 0, "out": 0}})
        return

    context, citations = _build_context(chunks)
    user_msg = f"Question: {question}\n\nContext:\n{context}"
    provider = get_chat_provider()

    parts: list[str] = []
    async for tok in provider.stream(ASK_SYSTEM, user_msg):
        parts.append(tok)
        yield _sse("token", {"text": tok})

    yield _sse("citations", {"items": citations})
    answer = "".join(parts)
    tin, tout = estimate_tokens(user_msg), estimate_tokens(answer)
    guard.record(tin + tout)
    yield _sse("done", {"answer_id": answer_id, "tokens": {"in": tin, "out": tout}})


# ---------------- Summarize / Extract (ephemeral artifacts) ----------------


async def _require_readable_page(
    session: AsyncSession, user: Principal, page_id: uuid.UUID
) -> tuple[Page, Space]:
    page = (await session.execute(select(Page).where(Page.id == page_id))).scalar_one_or_none()
    if page is None:
        raise NotFoundError("Page not found.", details={"page": str(page_id)})
    book = (await session.execute(select(Book).where(Book.id == page.book_id))).scalar_one()
    space = (await session.execute(select(Space).where(Space.id == book.space_id))).scalar_one()
    if not user.can(space.slug, Permission.READ):
        raise ForbiddenError("No read access.", details={"space": space.slug})
    return page, space


async def _page_markdown(
    session: AsyncSession, page_id: uuid.UUID, locale: str
) -> tuple[str, int, str]:
    rows = list(
        (
            await session.execute(select(PageTranslation).where(PageTranslation.page_id == page_id))
        ).scalars()
    )
    if not rows:
        raise NotFoundError("Page has no content.", details={"page": str(page_id)})
    by_locale = {t.locale: t for t in rows}
    chosen = by_locale.get(locale) or next(iter(by_locale.values()))
    return chosen.markdown, chosen.revision, chosen.locale


async def _store_artifact(
    session: AsyncSession, user: Principal, kind: str, markdown: str
) -> dict[str, Any]:
    ttl = get_settings().artifact_ttl_hours
    expires = datetime.now(UTC) + timedelta(hours=ttl)
    art = LlmArtifact(
        kind=kind, markdown=markdown, created_by=_as_uuid(user.sub), expires_at=expires
    )
    session.add(art)
    await session.flush()
    await session.commit()
    return {
        "artifact_id": art.id,
        "kind": kind,
        "markdown": markdown,
        "download": {"md": f"/api/v1/llm/artifacts/{art.id}/md"},
        "expires_at": expires,
    }


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def summarize(
    session: AsyncSession,
    user: Principal,
    guard: LlmGuard,
    *,
    target: dict[str, Any],
    style: str = "concise",
    locale: str = "en",
) -> dict[str, Any]:
    ttype = target.get("type")
    if ttype == "selection":
        text = target.get("text") or ""
    elif ttype == "page":
        await _require_readable_page(session, user, uuid.UUID(target["id"]))
        text, _, _ = await _page_markdown(session, uuid.UUID(target["id"]), locale)
    elif ttype == "book":
        text = await _book_markdown(session, user, uuid.UUID(target["id"]), locale)
    else:
        raise NotFoundError("Unknown summarize target.", details={"type": ttype})

    guard.check_budget(estimate_tokens(text))
    provider = get_chat_provider()
    md = await provider.complete(f"Summarize the documentation ({style}).", text)
    guard.record(estimate_tokens(text) + estimate_tokens(md))
    return await _store_artifact(session, user, "summary", md)


async def _book_markdown(
    session: AsyncSession, user: Principal, book_id: uuid.UUID, locale: str
) -> str:
    book = (await session.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
    if book is None:
        raise NotFoundError("Book not found.", details={"book": str(book_id)})
    space = (await session.execute(select(Space).where(Space.id == book.space_id))).scalar_one()
    if not user.can(space.slug, Permission.READ):
        raise ForbiddenError("No read access.", details={"space": space.slug})
    pages = list((await session.execute(select(Page).where(Page.book_id == book_id))).scalars())
    parts: list[str] = []
    for p in pages:
        md, _, _ = await _page_markdown(session, p.id, locale)
        parts.append(md)
    return "\n\n---\n\n".join(parts)


async def extract(
    session: AsyncSession,
    user: Principal,
    guard: LlmGuard,
    *,
    instruction: str,
    scope: str = "corpus",
    locale: str | None = None,
    fmt: str = "markdown_table",
) -> dict[str, Any]:
    chunks = await retrieve(session, user, q=instruction, scope=scope, locale=locale, k=8)
    context = "\n\n".join(ch.content for ch in chunks)
    guard.check_budget(estimate_tokens(context))
    provider = get_chat_provider()
    md = await provider.complete(
        f"Extract the requested information as {fmt}.",
        f"{instruction}\n\nContent:\n{context}",
    )
    guard.record(estimate_tokens(context) + estimate_tokens(md))
    return await _store_artifact(session, user, "extract", md)


async def get_artifact_markdown(session: AsyncSession, artifact_id: uuid.UUID) -> str:
    art = (
        await session.execute(select(LlmArtifact).where(LlmArtifact.id == artifact_id))
    ).scalar_one_or_none()
    if art is None or _is_expired(art.expires_at):
        raise NotFoundError("Artifact not found or expired.", details={"id": str(artifact_id)})
    return art.markdown


# ---------------- Translate (cached) ----------------


async def translate(
    session: AsyncSession,
    user: Principal,
    guard: LlmGuard,
    *,
    page_id: uuid.UUID,
    target_locale: str,
    source_locale: str | None = None,
) -> dict[str, Any]:
    await _require_readable_page(session, user, page_id)
    markdown, revision, served = await _page_markdown(session, page_id, source_locale or "en")

    cached = (
        await session.execute(
            select(TranslationCache).where(
                TranslationCache.page_id == page_id,
                TranslationCache.revision == revision,
                TranslationCache.locale == target_locale,
            )
        )
    ).scalar_one_or_none()
    if cached is not None and not _is_expired(cached.expires_at):
        return {
            "page_id": page_id,
            "target_locale": target_locale,
            "html": cached.html,
            "cached": True,
        }

    guard.check_budget(estimate_tokens(markdown))
    provider = get_chat_provider()
    translated_md = await provider.complete(
        f"Translate the following Markdown to {target_locale}. Preserve formatting.", markdown
    )
    guard.record(estimate_tokens(markdown) + estimate_tokens(translated_md))
    html, _ = render_markdown(translated_md)

    ttl = get_settings().artifact_ttl_hours
    session.add(
        TranslationCache(
            page_id=page_id,
            revision=revision,
            locale=target_locale,
            html=html,
            expires_at=datetime.now(UTC) + timedelta(hours=ttl),
        )
    )
    await session.commit()
    return {"page_id": page_id, "target_locale": target_locale, "html": html, "cached": False}


# ---------------- Feedback ----------------


async def record_feedback(
    session: AsyncSession,
    user: Principal,
    *,
    answer_id: uuid.UUID,
    rating: str,
    comment: str | None = None,
) -> None:
    session.add(
        AnalyticsEvent(
            type="llm_feedback",
            subject_id=answer_id,
            data={"rating": rating, "comment": comment, "by": user.sub},
        )
    )
    await session.commit()
