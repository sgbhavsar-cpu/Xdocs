"""Content read API integration tests (B2 + ACL/i18n: B-01, B-02, B-03, C-07, D-15)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app
from app.models.content import Page

READER = Principal(
    sub="reader-1",
    email="reader@example.com",
    locale="en",
    roles=[],
    global_permission=None,
    space_permissions={"sql-server": Permission.READ},
)
ADMIN = Principal(
    sub="admin-1",
    email="admin@example.com",
    locale="en",
    roles=["admin"],
    global_permission=Permission.ADMIN,
    space_permissions={},
)


def _as(user: Principal) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


async def _page_id(session: AsyncSession, slug: str) -> str:
    page = (await session.execute(select(Page).where(Page.slug == slug))).scalar_one()
    return str(page.id)


@pytest.mark.asyncio
async def test_spaces_acl_filtered(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/spaces")
    assert resp.status_code == 200
    slugs = {s["slug"] for s in resp.json()["items"]}
    assert slugs == {"sql-server"}  # platform hidden from reader (C-07)


@pytest.mark.asyncio
async def test_spaces_admin_sees_all(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(ADMIN)
    resp = await client.get("/api/v1/spaces")
    slugs = {s["slug"] for s in resp.json()["items"]}
    assert slugs == {"sql-server", "platform"}


@pytest.mark.asyncio
async def test_space_color_and_tree_sections(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(ADMIN)

    # Colour set by an admin surfaces on the read portal payload.
    await client.put("/api/v1/admin/spaces/sql-server", json={"color": "#0b5cad"})
    spaces = await client.get("/api/v1/spaces")
    row = next(s for s in spaces.json()["items"] if s["slug"] == "sql-server")
    assert row["color"] == "#0b5cad"

    # Group a published page under a section and confirm the reader tree shows it.
    from app.models.content import Book

    bid = str((await session.execute(select(Book).where(Book.slug == "t-sql"))).scalar_one().id)
    sec = await client.post("/api/v1/admin/sections", json={"book_id": bid, "title": "Statements"})
    section_id = sec.json()["id"]
    page = await client.post(
        "/api/v1/admin/pages",
        json={"book_id": bid, "slug": "update", "title": "UPDATE", "section_id": section_id},
    )
    await client.post(f"/api/v1/admin/pages/{page.json()['id']}/publish")

    tree = await client.get("/api/v1/spaces/sql-server/tree")
    assert tree.status_code == 200
    book = next(b for b in tree.json()["books"] if b["id"] == bid)
    section = next(s for s in book["sections"] if s["id"] == section_id)
    assert any(p["title"] == "UPDATE" for p in section["pages"])


@pytest.mark.asyncio
async def test_space_default_and_visible_versions(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/spaces")
    sql = next(s for s in resp.json()["items"] if s["slug"] == "sql-server")
    assert sql["default_version"]["label"] == "2022"
    labels = {v["label"] for v in sql["visible_versions"]}
    assert labels == {"2019", "2022"}  # internal "vNext" hidden (§16.5)


@pytest.mark.asyncio
async def test_tree_structure(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/spaces/sql-server/tree")
    assert resp.status_code == 200
    tree = resp.json()
    book_slugs = {b["slug"] for b in tree["books"]}
    assert {"guide", "t-sql"} <= book_slugs
    tsql = next(b for b in tree["books"] if b["slug"] == "t-sql")
    select_node = next(p for p in tsql["pages"] if p["slug"] == "select")
    assert select_node["has_children"] is True
    assert any(c["slug"] == "select-into" for c in select_node["children"])


@pytest.mark.asyncio
async def test_get_page_renders(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as(READER)
    pid = await _page_id(session, "select")
    resp = await client.get(f"/api/v1/pages/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert "SELECT" in body["html"]
    assert any(h["id"] == "syntax" for h in body["headings"])
    assert body["fallback"] is None


@pytest.mark.asyncio
async def test_missing_locale_falls_back(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(READER)
    pid = await _page_id(session, "getting-started")
    resp = await client.get(f"/api/v1/pages/{pid}?locale=de")
    body = resp.json()
    assert body["locale"] == "en"  # served default
    assert body["fallback"]["requested_locale"] == "de"
    assert body["fallback"]["can_auto_translate"] is True


@pytest.mark.asyncio
async def test_french_translation_served(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(READER)
    pid = await _page_id(session, "getting-started")
    resp = await client.get(f"/api/v1/pages/{pid}?locale=fr")
    body = resp.json()
    assert body["locale"] == "fr"
    assert body["title"] == "Prise en main"


@pytest.mark.asyncio
async def test_reader_denied_platform_tree(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/spaces/platform/tree")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
