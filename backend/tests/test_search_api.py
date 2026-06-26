"""Search API integration tests (C3–C5: C-03, C-04, C-05, C-06, C-07, C-08, C-10)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app

READER = Principal(
    sub="reader-1",
    email="r@x",
    locale="en",
    roles=[],
    global_permission=None,
    space_permissions={"sql-server": Permission.READ},
)
ADMIN = Principal(
    sub="admin-1",
    email="a@x",
    locale="en",
    roles=["admin"],
    global_permission=Permission.ADMIN,
    space_permissions={},
)


def _as(user: Principal) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.mark.asyncio
async def test_keyword_search_finds_page(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/search", params={"q": "select into"})
    assert resp.status_code == 200
    body = resp.json()
    titles = [r["title"] for r in body["results"]]
    assert any("SELECT INTO" == t for t in titles)
    # snippet highlights the query term
    top = body["results"][0]
    assert "<em>" in top["snippet"]


@pytest.mark.asyncio
async def test_search_returns_anchor_for_deeplink(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/search", params={"q": "creating a table"})
    results = resp.json()["results"]
    into = next(r for r in results if r["title"] == "SELECT INTO")
    assert into["best_anchor"] == "creating-a-table"


@pytest.mark.asyncio
async def test_search_acl_excludes_platform(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/search", params={"q": "platform overview"})
    spaces = {r["space"] for r in resp.json()["results"]}
    assert "platform" not in spaces  # C-07


@pytest.mark.asyncio
async def test_admin_search_sees_platform(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(ADMIN)
    resp = await client.get("/api/v1/search", params={"q": "platform overview"})
    spaces = {r["space"] for r in resp.json()["results"]}
    assert "platform" in spaces


@pytest.mark.asyncio
async def test_scope_limits_results(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(ADMIN)
    resp = await client.get("/api/v1/search", params={"q": "overview", "scope": "space:sql-server"})
    spaces = {r["space"] for r in resp.json()["results"]}
    assert spaces <= {"sql-server"}


@pytest.mark.asyncio
async def test_zero_results(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/search", params={"q": "zzzqqq nonexistentterm"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []  # C-10


@pytest.mark.asyncio
async def test_suggest_prefix(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(READER)
    resp = await client.get("/api/v1/search/suggest", params={"q": "SEL"})
    items = resp.json()["items"]
    assert items
    assert all(i["title"].lower().startswith("sel") for i in items)
