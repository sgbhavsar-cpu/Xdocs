"""Export assembly: build print HTML, render to PDF, persist the job (E1/E2)."""

from __future__ import annotations

import hashlib
import hmac
import html as html_lib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission, Principal
from app.content.render import render_markdown
from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError
from app.export.pdf import get_pdf_renderer
from app.models.content import Book, Page, PageTranslation, Space
from app.models.export import ExportJob
from app.models.llm import LlmArtifact

_PRINT_CSS = """
@page { size: A4; margin: 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: ui-sans-serif, system-ui, sans-serif; color: #1f2937; line-height: 1.55; }
h1 { font-size: 1.8rem; margin: 0 0 .6rem; }
h2 { font-size: 1.35rem; margin: 1.4rem 0 .5rem; }
h3 { font-size: 1.1rem; margin: 1rem 0 .4rem; }
pre { background: #f4f5f7; border: 1px solid #e5e7eb; border-radius: 6px; padding: .7rem;
      white-space: pre-wrap; word-wrap: break-word; }
code { font-family: ui-monospace, Menlo, monospace; font-size: .9em; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #e5e7eb; padding: .35rem .55rem; text-align: left; }
img { max-width: 100%; }
.doc-cover { text-align: center; padding-top: 30%; }
.doc-cover h1 { font-size: 2.4rem; }
.doc-toc { page-break-after: always; }
.doc-page + .doc-page { page-break-before: always; }
"""


def _document(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html_lib.escape(title)}</title><style>{_PRINT_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


async def _page_html(session: AsyncSession, page_id: uuid.UUID, locale: str) -> tuple[str, str]:
    rows = list(
        (
            await session.execute(select(PageTranslation).where(PageTranslation.page_id == page_id))
        ).scalars()
    )
    if not rows:
        raise NotFoundError("Page has no content.", details={"page": str(page_id)})
    by_locale = {t.locale: t for t in rows}
    tr = by_locale.get(locale) or next(iter(by_locale.values()))
    if tr.html_cached:
        return tr.title, tr.html_cached
    html, _ = render_markdown(tr.markdown)
    return tr.title, html


async def _require_space(session: AsyncSession, user: Principal, space: Space) -> None:
    if not user.can(space.slug, Permission.READ):
        raise ForbiddenError("No read access.", details={"space": space.slug})


async def _ordered_pages(session: AsyncSession, book_id: uuid.UUID) -> list[Page]:
    return list(
        (
            await session.execute(
                select(Page)
                .where(Page.book_id == book_id, Page.status == "published")
                .order_by(Page.sort_order)
            )
        ).scalars()
    )


async def build_html(
    session: AsyncSession,
    user: Principal,
    *,
    scope_type: str,
    scope_id: str,
    locale: str = "en",
) -> tuple[str, str, int]:
    """Return (title, html, page_count). Performs ACL checks (raises 403/404)."""
    if scope_type == "page":
        page = (
            await session.execute(select(Page).where(Page.id == uuid.UUID(scope_id)))
        ).scalar_one_or_none()
        if page is None:
            raise NotFoundError("Page not found.", details={"page": scope_id})
        book = (await session.execute(select(Book).where(Book.id == page.book_id))).scalar_one()
        space = (await session.execute(select(Space).where(Space.id == book.space_id))).scalar_one()
        await _require_space(session, user, space)
        title, body = await _page_html(session, page.id, locale)
        return title, _document(title, f"<section class='doc-page'>{body}</section>"), 1

    if scope_type == "book":
        bk = (
            await session.execute(select(Book).where(Book.id == uuid.UUID(scope_id)))
        ).scalar_one_or_none()
        if bk is None:
            raise NotFoundError("Book not found.", details={"book": scope_id})
        bspace = (await session.execute(select(Space).where(Space.id == bk.space_id))).scalar_one()
        await _require_space(session, user, bspace)
        pages = await _ordered_pages(session, bk.id)
        sections, toc = [], []
        for p in pages:
            t, body = await _page_html(session, p.id, locale)
            toc.append(f"<li>{html_lib.escape(t)}</li>")
            sections.append(f"<section class='doc-page'>{body}</section>")
        cover = f"<div class='doc-cover'><h1>{html_lib.escape(bk.title)}</h1></div>"
        toc_html = f"<nav class='doc-toc'><h2>Contents</h2><ol>{''.join(toc)}</ol></nav>"
        return bk.title, _document(bk.title, cover + toc_html + "".join(sections)), len(pages)

    if scope_type == "space":
        sp = (
            await session.execute(select(Space).where(Space.slug == scope_id))
        ).scalar_one_or_none()
        if sp is None:
            raise NotFoundError("Space not found.", details={"space": scope_id})
        await _require_space(session, user, sp)
        books = list((await session.execute(select(Book).where(Book.space_id == sp.id))).scalars())
        sections, count = [], 0
        for b in books:
            sections.append(f"<h1>{html_lib.escape(b.title)}</h1>")
            for p in await _ordered_pages(session, b.id):
                _, body = await _page_html(session, p.id, locale)
                sections.append(f"<section class='doc-page'>{body}</section>")
                count += 1
        cover = f"<div class='doc-cover'><h1>{html_lib.escape(sp.title)}</h1></div>"
        return sp.title, _document(sp.title, cover + "".join(sections)), count

    if scope_type == "artifact":
        art = (
            await session.execute(select(LlmArtifact).where(LlmArtifact.id == uuid.UUID(scope_id)))
        ).scalar_one_or_none()
        if art is None:
            raise NotFoundError("Artifact not found.", details={"id": scope_id})
        body, _ = render_markdown(art.markdown)
        return art.kind, _document(art.kind, f"<section class='doc-page'>{body}</section>"), 1

    raise NotFoundError("Unknown export scope.", details={"type": scope_type})


async def create_and_render(
    session: AsyncSession,
    user: Principal,
    *,
    scope_type: str,
    scope_id: str,
    locale: str = "en",
) -> ExportJob:
    # Build (and ACL-check) before creating the job so failures surface as 403/404.
    _, html, page_count = await build_html(
        session, user, scope_type=scope_type, scope_id=scope_id, locale=locale
    )
    ttl = get_settings().export_ttl_hours
    job = ExportJob(
        scope_type=scope_type,
        scope_id=scope_id,
        status="rendering",
        page_count=page_count,
        created_by=_as_uuid(user.sub),
        expires_at=datetime.now(UTC) + timedelta(hours=ttl),
    )
    session.add(job)
    await session.flush()
    try:
        job.content = await get_pdf_renderer().render(html)
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 - record failure on the job
        job.status = "failed"
        job.error = str(exc)
    await session.commit()
    return job


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _sign(job_id: uuid.UUID, expires: int) -> str:
    secret = get_settings().export_signing_secret.encode()
    msg = f"{job_id}:{expires}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify_signature(job_id: uuid.UUID, expires: int, sig: str) -> None:
    """Validate a signed download URL (time-limited, tamper-proof)."""
    if expires < int(datetime.now(UTC).timestamp()):
        raise ForbiddenError("Download link has expired.")
    if not hmac.compare_digest(_sign(job_id, expires), sig):
        raise ForbiddenError("Invalid download signature.")


def job_summary(job: ExportJob) -> dict[str, Any]:
    url = None
    if job.status == "done":
        # Signed, time-limited URL usable without an auth header (downloads/new tab).
        expires = int(
            (datetime.now(UTC) + timedelta(hours=get_settings().export_ttl_hours)).timestamp()
        )
        sig = _sign(job.id, expires)
        url = f"/api/v1/export/{job.id}/download?expires={expires}&sig={sig}"
    return {
        "job_id": job.id,
        "status": job.status,
        "url": url,
        "page_count": job.page_count,
        "expires_at": job.expires_at,
        "error": job.error,
    }


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> ExportJob:
    job = (
        await session.execute(select(ExportJob).where(ExportJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("Export job not found.", details={"id": str(job_id)})
    return job


async def get_pdf(session: AsyncSession, job_id: uuid.UUID) -> bytes:
    job = await get_job(session, job_id)
    expires = job.expires_at
    now = datetime.now(UTC) if expires.tzinfo else datetime.now(UTC).replace(tzinfo=None)
    if job.status != "done" or job.content is None or expires < now:
        raise NotFoundError("Export not available.", details={"id": str(job_id)})
    return job.content
