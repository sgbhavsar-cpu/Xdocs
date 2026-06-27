"""PDF import tests (F7): outline -> pages, image -> media, ACL."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from httpx import AsyncClient
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app
from app.models.content import Book, Space

EDITOR = Principal(
    sub="00000000-0000-0000-0000-0000000000ee",
    email="e@x",
    locale="en",
    roles=[],
    global_permission=None,
    space_permissions={"sql-server": Permission.WRITE},
)
READER = Principal(
    sub="00000000-0000-0000-0000-0000000000aa",
    email="r@x",
    locale="en",
    roles=[],
    global_permission=None,
    space_permissions={"sql-server": Permission.READ},
)


def _png(w: int = 3, h: int = 3) -> bytes:
    """A tiny valid RGB PNG (so reportlab can embed and pdfminer can extract it)."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))  # red rows, filter 0

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _pdf_with_outline_and_image() -> bytes:
    """Two top-level bookmarks (Introduction, Usage) across two pages; the first
    page embeds an image. Headings use a large font so size-based detection fires."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    img = ImageReader(io.BytesIO(_png()))

    c.bookmarkPage("sec-intro")
    c.addOutlineEntry("Introduction", "sec-intro", level=0)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(72, 720, "Introduction")
    c.setFont("Helvetica", 12)
    c.drawString(72, 690, "This is the introduction paragraph body text.")
    c.drawImage(img, 72, 560, width=96, height=96)
    c.showPage()

    c.bookmarkPage("sec-usage")
    c.addOutlineEntry("Usage", "sec-usage", level=0)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(72, 720, "Usage")
    c.setFont("Helvetica", 12)
    c.drawString(72, 690, "Body text describing usage of the product.")
    c.showPage()
    c.save()
    return buf.getvalue()


async def _first_book_id(session: AsyncSession) -> str:
    book = (
        await session.execute(
            select(Book).join(Space, Book.space_id == Space.id).where(Space.slug == "sql-server")
        )
    ).scalars().first()
    assert book is not None
    return str(book.id)


def _as(user: Principal) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.mark.asyncio
async def test_import_splits_by_outline_and_extracts_image(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    book_id = await _first_book_id(session)

    resp = await client.post(
        "/api/v1/admin/import/pdf",
        files={"file": ("Guide.pdf", _pdf_with_outline_and_image(), "application/pdf")},
        data={"book_id": book_id, "locale": "en"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Outline -> one page per top-level bookmark.
    assert body["count"] == 2
    titles = [p["title"] for p in body["pages"]]
    assert titles == ["Introduction", "Usage"]

    # First page: heading detected + image extracted to a media reference.
    intro = await client.get(f"/api/v1/admin/pages/{body['pages'][0]['id']}/translations/en")
    assert intro.status_code == 200
    md = intro.json()["markdown"]
    assert "# Introduction" in md
    assert "/api/v1/media/" in md  # embedded image became a media asset reference

    # The referenced media actually serves.
    url = md.split("](", 1)[1].split(")", 1)[0]
    served = await client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/")

    # Imported pages are drafts until the author publishes.
    tree = (await client.get("/api/v1/admin/spaces/sql-server/tree")).json()
    statuses = {p["title"]: p["status"] for b in tree["books"] for p in b["pages"]}
    assert statuses.get("Introduction") == "draft"


@pytest.mark.asyncio
async def test_import_requires_write(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    book_id = await _first_book_id(session)
    _as(READER)
    resp = await client.post(
        "/api/v1/admin/import/pdf",
        files={"file": ("Guide.pdf", _pdf_with_outline_and_image(), "application/pdf")},
        data={"book_id": book_id, "locale": "en"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_import_pdf_as_new_book(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(EDITOR)
    resp = await client.post(
        "/api/v1/admin/spaces/sql-server/books/import-pdf",
        files={"file": ("Handbook.pdf", _pdf_with_outline_and_image(), "application/pdf")},
        data={"locale": "en"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # A new book titled from the filename, with the PDF's sections as draft pages.
    assert body["book"]["title"] == "Handbook"
    assert body["count"] == 2
    tree = (await client.get("/api/v1/admin/spaces/sql-server/tree")).json()
    book = next(b for b in tree["books"] if b["id"] == body["book"]["id"])
    assert {p["title"] for p in book["pages"]} == {"Introduction", "Usage"}
    assert all(p["status"] == "draft" for p in book["pages"])


@pytest.mark.asyncio
async def test_import_pdf_as_markdown_into_page(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(EDITOR)
    resp = await client.post(
        "/api/v1/admin/spaces/sql-server/import-pdf-markdown",
        files={"file": ("Guide.pdf", _pdf_with_outline_and_image(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # No pages are created — just Markdown for insertion into the open editor.
    md = body["markdown"]
    assert "# Introduction" in md
    assert "Usage" in md
    # The embedded image became a media asset reference that actually serves.
    url = md.split("](", 1)[1].split(")", 1)[0]
    served = await client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/")


@pytest.mark.asyncio
async def test_import_pdf_as_markdown_requires_write(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.post(
        "/api/v1/admin/spaces/sql-server/import-pdf-markdown",
        files={"file": ("Guide.pdf", _pdf_with_outline_and_image(), "application/pdf")},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_import_rejects_non_pdf(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    book_id = await _first_book_id(session)
    _as(EDITOR)
    resp = await client.post(
        "/api/v1/admin/import/pdf",
        files={"file": ("notes.txt", b"just text, not a pdf", "application/pdf")},
        data={"book_id": book_id, "locale": "en"},
    )
    assert resp.status_code == 422
