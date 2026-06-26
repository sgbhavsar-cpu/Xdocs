"""Export API tests (E1/E2: E-01, E-02, E-05, E-06, E-07 + ACL)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app
from app.models.content import Book, Page

READER = Principal(
    sub="00000000-0000-0000-0000-0000000000aa",
    email="r@x",
    locale="en",
    roles=[],
    global_permission=None,
    space_permissions={"sql-server": Permission.READ},
)


def _as(user: Principal = READER) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


async def _page_id(session: AsyncSession, slug: str) -> str:
    return str((await session.execute(select(Page).where(Page.slug == slug))).scalar_one().id)


async def _book_id(session: AsyncSession, slug: str) -> str:
    return str((await session.execute(select(Book).where(Book.slug == slug))).scalar_one().id)


@pytest.mark.asyncio
async def test_export_page_then_download(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as()
    pid = await _page_id(session, "select")
    resp = await client.post("/api/v1/export", json={"scope": {"type": "page", "id": pid}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["url"]
    dl = await client.get(body["url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/pdf"
    assert dl.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_signed_url_required(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as()
    pid = await _page_id(session, "select")
    body = (await client.post("/api/v1/export", json={"scope": {"type": "page", "id": pid}})).json()
    # Tampering with the signature is rejected (E-05).
    bad = body["url"].rsplit("sig=", 1)[0] + "sig=deadbeef"
    resp = await client.get(bad)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_export_book_page_count(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as()
    bid = await _book_id(session, "t-sql")
    resp = await client.post("/api/v1/export", json={"scope": {"type": "book", "id": bid}})
    body = resp.json()
    assert body["status"] == "done"
    assert body["page_count"] >= 2  # select + select-into (E-02)


@pytest.mark.asyncio
async def test_export_status_endpoint(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as()
    pid = await _page_id(session, "select")
    job = (await client.post("/api/v1/export", json={"scope": {"type": "page", "id": pid}})).json()
    status = await client.get(f"/api/v1/export/{job['job_id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "done"


@pytest.mark.asyncio
async def test_export_acl_denied(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as()  # reader cannot read platform
    ppid = await _page_id(session, "overview")  # platform page
    resp = await client.post("/api/v1/export", json={"scope": {"type": "page", "id": ppid}})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_export_artifact(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as()
    pid = await _page_id(session, "select")
    art = (
        await client.post("/api/v1/llm/summarize", json={"target": {"type": "page", "id": pid}})
    ).json()
    resp = await client.post(
        "/api/v1/export", json={"scope": {"type": "artifact", "id": str(art["artifact_id"])}}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"  # E-06
