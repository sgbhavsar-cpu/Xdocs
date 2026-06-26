"""Analytics + hardening tests (H1, H3, H4): H-01, H-02, B-04, plus headers."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app
from app.models.content import Page

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


async def _page_id(session: AsyncSession, slug: str) -> str:
    return str((await session.execute(select(Page).where(Page.slug == slug))).scalar_one().id)


@pytest.mark.asyncio
async def test_pageviews_recorded_and_ranked(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(READER)
    pid = await _page_id(session, "select")
    other = await _page_id(session, "getting-started")
    for _ in range(3):
        await client.post("/api/v1/analytics/pageview", json={"page_id": pid})
    await client.post("/api/v1/analytics/pageview", json={"page_id": other})

    _as(EDITOR)
    resp = await client.get("/api/v1/admin/analytics/pageviews")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items[0]["title"] == "SELECT statement"  # most viewed first (H-01)
    assert items[0]["views"] == 3


@pytest.mark.asyncio
async def test_feedback_summary(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(READER)
    await client.post(
        "/api/v1/llm/feedback",
        json={"answer_id": "11111111-1111-1111-1111-111111111111", "rating": "up"},
    )
    await client.post(
        "/api/v1/llm/feedback",
        json={
            "answer_id": "22222222-2222-2222-2222-222222222222",
            "rating": "down",
            "comment": "off",
        },
    )
    _as(EDITOR)
    resp = await client.get("/api/v1/admin/analytics/llm-feedback")
    body = resp.json()
    assert body["up"] == 1 and body["down"] == 1 and body["total"] == 2  # H-02
    assert body["comments"][0]["comment"] == "off"


@pytest.mark.asyncio
async def test_reader_cannot_view_dashboards(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/admin/analytics/pageviews")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_etag_conditional_get(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as(READER)
    pid = await _page_id(session, "select")
    first = await client.get(f"/api/v1/pages/{pid}")
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag
    second = await client.get(f"/api/v1/pages/{pid}", headers={"If-None-Match": etag})
    assert second.status_code == 304  # B-04 / H3


@pytest.mark.asyncio
async def test_security_headers(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    resp = await client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
