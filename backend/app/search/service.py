"""Search indexing and hybrid query (C1–C5).

Indexing: split published translations into chunks, embed them, and store them in
`doc_chunk` (denormalized for fast scope/ACL filtering).

Query: hybrid keyword + semantic search. Keyword matching and cosine similarity
are computed in the application and fused with Reciprocal Rank Fusion (RRF), then
grouped by page with a highlighted snippet. This is correct and fully testable on
SQLite; for production scale the Postgres FTS GIN index (migration 0003) and the
pgvector/HNSW path (design §5) are the optimization targets behind this interface.
"""

from __future__ import annotations

import html
import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, Principal
from app.llm.embeddings import cosine, get_embedding_provider
from app.models.content import Book, DocChunk, Page, PageTranslation, Space
from app.search.chunking import chunk_markdown

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_RRF_K = 60
# Minimum cosine for a keyword-less chunk to still count as a semantic match.
# Keeps irrelevant queries returning nothing rather than nearest-neighbor noise.
_VEC_THRESHOLD = 0.2


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# ---------------- Indexing ----------------


async def reindex_all(session: AsyncSession) -> int:
    """Rebuild the entire search index from published pages. Returns chunk count."""
    await session.execute(delete(DocChunk))

    pages = list((await session.execute(select(Page))).scalars())
    books = {b.id: b for b in (await session.execute(select(Book))).scalars()}
    spaces = {s.id: s for s in (await session.execute(select(Space))).scalars()}
    translations = list((await session.execute(select(PageTranslation))).scalars())
    trans_by_page: dict[uuid.UUID, list[PageTranslation]] = defaultdict(list)
    for t in translations:
        trans_by_page[t.page_id].append(t)

    provider = get_embedding_provider()
    total = 0
    for page in pages:
        if page.status != "published":
            continue
        book = books.get(page.book_id)
        if book is None:
            continue
        space = spaces.get(book.space_id)
        if space is None:
            continue
        for tr in trans_by_page.get(page.id, []):
            chunks = chunk_markdown(tr.markdown)
            if not chunks:
                continue
            embeddings = await provider.embed([c["content"] for c in chunks])
            for c, emb in zip(chunks, embeddings, strict=False):
                session.add(
                    DocChunk(
                        page_translation_id=tr.id,
                        page_id=page.id,
                        space_slug=space.slug,
                        book_id=book.id,
                        locale=tr.locale,
                        page_title=tr.title,
                        ordinal=c["ordinal"],
                        content=c["content"],
                        anchor=c["anchor"],
                        embedding=emb,
                    )
                )
                total += 1
    return total


# ---------------- Query ----------------


async def _readable_spaces(session: AsyncSession, user: Principal) -> set[str]:
    slugs = list((await session.execute(select(Space.slug))).scalars())
    return {s for s in slugs if user.can(s, Permission.READ)}


def _scope_predicate(scope: str) -> tuple[str, str] | None:
    """Parse a scope string into a (field, value) filter, or None for corpus."""
    if not scope or scope == "corpus":
        return None
    kind, _, value = scope.partition(":")
    if kind == "space":
        return ("space_slug", value)
    if kind == "book":
        return ("book_id", value)
    if kind == "page":
        return ("page_id", value)
    return None


def _keyword_score(query_tokens: set[str], content: str, title: str) -> float:
    content_tokens = set(_tokens(content))
    title_tokens = set(_tokens(title))
    hits = len(query_tokens & content_tokens)
    title_hits = len(query_tokens & title_tokens)
    return float(hits + 2 * title_hits)


def _snippet(content: str, query_tokens: set[str], width: int = 200) -> str:
    lower = content.lower()
    pos = -1
    for tok in query_tokens:
        i = lower.find(tok)
        if i != -1 and (pos == -1 or i < pos):
            pos = i
    start = max(0, pos - width // 3) if pos != -1 else 0
    excerpt = content[start : start + width].strip()
    safe = html.escape(excerpt)
    for tok in sorted(query_tokens, key=len, reverse=True):
        safe = re.sub(f"({re.escape(html.escape(tok))})", r"<em>\1</em>", safe, flags=re.IGNORECASE)
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + width < len(content) else ""
    return f"{prefix}{safe}{suffix}"


async def search(
    session: AsyncSession,
    user: Principal,
    *,
    q: str,
    scope: str = "corpus",
    locale: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    allowed = await _readable_spaces(session, user)
    if not allowed or not q.strip():
        return []

    stmt = select(DocChunk).where(DocChunk.space_slug.in_(allowed))
    pred = _scope_predicate(scope)
    if pred:
        field, value = pred
        column = getattr(DocChunk, field)
        # book_id/page_id are UUIDs; coerce for comparison.
        stmt = stmt.where(column == (uuid.UUID(value) if field.endswith("_id") else value))
    if locale:
        stmt = stmt.where(DocChunk.locale == locale)

    chunks = list((await session.execute(stmt)).scalars())
    if not chunks:
        return []

    query_tokens = set(_tokens(q))
    qemb = (await get_embedding_provider().embed([q]))[0]

    kw_scores: dict[uuid.UUID, float] = {}
    vec_scores: dict[uuid.UUID, float] = {}
    for ch in chunks:
        kw_scores[ch.id] = _keyword_score(query_tokens, ch.content, ch.page_title)
        vec_scores[ch.id] = cosine(qemb, ch.embedding or [])

    # A chunk qualifies if it matches by keyword or is semantically close enough,
    # so irrelevant queries return nothing instead of nearest-neighbor noise.
    candidates = [
        ch.id for ch in chunks if kw_scores[ch.id] > 0 or vec_scores[ch.id] >= _VEC_THRESHOLD
    ]
    if not candidates:
        return []

    kw_ranked = [
        cid
        for cid in sorted(candidates, key=lambda c: kw_scores[c], reverse=True)
        if kw_scores[cid] > 0
    ]
    vec_ranked = sorted(candidates, key=lambda c: vec_scores[c], reverse=True)

    rrf: dict[uuid.UUID, float] = defaultdict(float)
    for ranked in (kw_ranked, vec_ranked):
        for rank, cid in enumerate(ranked):
            rrf[cid] += 1.0 / (_RRF_K + rank + 1)

    by_id = {ch.id: ch for ch in chunks}
    # Group by page, keeping the best-scoring chunk per page.
    best_per_page: dict[uuid.UUID, tuple[float, DocChunk]] = {}
    for cid, score in rrf.items():
        ch = by_id[cid]
        cur = best_per_page.get(ch.page_id)
        if cur is None or score > cur[0]:
            best_per_page[ch.page_id] = (score, ch)

    ordered = sorted(best_per_page.values(), key=lambda x: x[0], reverse=True)[:limit]
    results = []
    for score, ch in ordered:
        anchor = (ch.anchor or {}).get("heading_id") if ch.anchor else None
        results.append(
            {
                "page_id": ch.page_id,
                "title": ch.page_title,
                "space": ch.space_slug,
                "book_id": ch.book_id,
                "locale": ch.locale,
                "best_anchor": anchor,
                "snippet": _snippet(ch.content, query_tokens),
                "score": round(score, 6),
            }
        )
    return results


async def suggest(
    session: AsyncSession, user: Principal, *, q: str, scope: str = "corpus", limit: int = 8
) -> list[dict[str, Any]]:
    allowed = await _readable_spaces(session, user)
    if not allowed or not q.strip():
        return []
    stmt = (
        select(DocChunk.page_id, DocChunk.page_title, DocChunk.space_slug)
        .where(DocChunk.space_slug.in_(allowed))
        .where(DocChunk.page_title.ilike(f"{q}%"))
        .distinct()
        .limit(limit)
    )
    pred = _scope_predicate(scope)
    if pred and pred[0] == "space_slug":
        stmt = stmt.where(DocChunk.space_slug == pred[1])
    rows = (await session.execute(stmt)).all()
    return [{"page_id": pid, "title": title, "space": space} for pid, title, space in rows]
