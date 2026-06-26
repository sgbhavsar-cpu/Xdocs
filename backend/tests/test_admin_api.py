"""Admin/CMS API tests (F2–F4, F6): F-02..F-08."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app
from app.models.content import Book, Page

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


def _as(user: Principal) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


async def _book_id(session: AsyncSession, slug: str) -> str:
    return str((await session.execute(select(Book).where(Book.slug == slug))).scalar_one().id)


async def _page_id(session: AsyncSession, slug: str) -> str:
    return str((await session.execute(select(Page).where(Page.slug == slug))).scalar_one().id)


@pytest.mark.asyncio
async def test_preview_matches_renderer(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(EDITOR)
    resp = await client.post("/api/v1/admin/preview", json={"markdown": "# Hi\n\n## Sub"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'id="sub"' in body["html"]
    assert any(h["id"] == "sub" for h in body["headings"])


@pytest.mark.asyncio
async def test_reader_cannot_author(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as(READER)
    bid = await _book_id(session, "t-sql")
    resp = await client.post(
        "/api/v1/admin/pages", json={"book_id": bid, "slug": "x", "title": "X"}
    )
    assert resp.status_code == 403  # F-02


@pytest.mark.asyncio
async def test_create_edit_publish_flow(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    bid = await _book_id(session, "t-sql")

    # Create page (draft) — not visible to readers yet.
    created = await client.post(
        "/api/v1/admin/pages",
        json={"book_id": bid, "slug": "merge", "title": "MERGE", "markdown": "# MERGE\n\n## Use"},
    )
    assert created.status_code == 200
    page_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    # Draft is not searchable.
    _as(READER)
    s = await client.get("/api/v1/search", params={"q": "MERGE"})
    assert all(r["title"] != "MERGE" for r in s.json()["results"])  # F-05 draft hidden

    # Publish.
    _as(EDITOR)
    pub = await client.post(f"/api/v1/admin/pages/{page_id}/publish")
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["indexed_chunks"] >= 1

    # Now reader can read + search it (F-06).
    _as(READER)
    page = await client.get(f"/api/v1/pages/{page_id}")
    assert page.status_code == 200
    assert "MERGE" in page.json()["html"]
    s2 = await client.get("/api/v1/search", params={"q": "MERGE"})
    assert any(r["title"] == "MERGE" for r in s2.json()["results"])


@pytest.mark.asyncio
async def test_optimistic_lock_conflict(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as(EDITOR)
    pid = await _page_id(session, "select")
    # Current revision is 1; saving with a stale base_revision conflicts.
    resp = await client.put(
        f"/api/v1/admin/pages/{pid}/translations/en",
        json={"markdown": "# changed", "base_revision": 99},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "revision_conflict"  # F-08


@pytest.mark.asyncio
async def test_revision_history_and_restore(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    pid = await _page_id(session, "select")

    # Edit twice.
    r1 = await client.put(
        f"/api/v1/admin/pages/{pid}/translations/en",
        json={"markdown": "# v2", "base_revision": 1},
    )
    assert r1.json()["revision"] == 2
    await client.put(
        f"/api/v1/admin/pages/{pid}/translations/en",
        json={"markdown": "# v3", "base_revision": 2},
    )

    revs = await client.get(f"/api/v1/admin/pages/{pid}/revisions", params={"locale": "en"})
    assert len(revs.json()["items"]) >= 3  # F-07

    # Restore revision 2's content.
    await client.post(f"/api/v1/admin/pages/{pid}/revisions/2/restore", params={"locale": "en"})
    cur = await client.get(f"/api/v1/admin/pages/{pid}/translations/en")
    assert cur.json()["markdown"] == "# v2"


@pytest.mark.asyncio
async def test_admin_tree_includes_drafts(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    bid = await _book_id(session, "t-sql")
    await client.post(
        "/api/v1/admin/pages", json={"book_id": bid, "slug": "draftpage", "title": "Draft Page"}
    )
    tree = await client.get("/api/v1/admin/spaces/sql-server/tree")
    titles = [p["title"] for b in tree.json()["books"] for p in b["pages"]]
    assert "Draft Page" in titles
