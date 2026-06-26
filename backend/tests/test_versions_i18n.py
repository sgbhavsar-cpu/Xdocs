"""Versions + i18n tests (G1–G4): G-01..G-08."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app
from app.models.content import Page, ProductVersion, Space

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


async def _space_id(session: AsyncSession, slug: str) -> str:
    return str((await session.execute(select(Space).where(Space.slug == slug))).scalar_one().id)


async def _version_id(session: AsyncSession, label: str) -> str:
    return str(
        (await session.execute(select(ProductVersion).where(ProductVersion.label == label)))
        .scalar_one()
        .id
    )


async def _page_id(session: AsyncSession, slug: str) -> str:
    return str((await session.execute(select(Page).where(Page.slug == slug))).scalar_one().id)


@pytest.mark.asyncio
async def test_tree_reports_locales(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as(READER)
    tree = await client.get("/api/v1/spaces/sql-server/tree")
    assert set(tree.json()["locales"]) >= {"en", "fr"}  # G-05


@pytest.mark.asyncio
async def test_internal_version_hidden_until_published(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    # vNext is internal in the seed.
    _as(READER)
    spaces = await client.get("/api/v1/spaces")
    sql = next(s for s in spaces.json()["items"] if s["slug"] == "sql-server")
    assert "vNext" not in {v["label"] for v in sql["visible_versions"]}  # G-01

    # Publish vNext; now visible.
    _as(EDITOR)
    vid = await _version_id(session, "vNext")
    await client.put(f"/api/v1/admin/versions/{vid}", json={"visibility": "published"})
    _as(READER)
    spaces2 = await client.get("/api/v1/spaces")
    sql2 = next(s for s in spaces2.json()["items"] if s["slug"] == "sql-server")
    assert "vNext" in {v["label"] for v in sql2["visible_versions"]}


@pytest.mark.asyncio
async def test_set_default_version(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as(EDITOR)
    vid = await _version_id(session, "2019")
    await client.put(f"/api/v1/admin/versions/{vid}", json={"is_default": True})
    _as(READER)
    spaces = await client.get("/api/v1/spaces")
    sql = next(s for s in spaces.json()["items"] if s["slug"] == "sql-server")
    assert sql["default_version"]["label"] == "2019"  # G-02


@pytest.mark.asyncio
async def test_clone_version(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as(EDITOR)
    vid = await _version_id(session, "2022")
    resp = await client.post(f"/api/v1/admin/versions/{vid}/clone", json={"label": "2025"})
    assert resp.status_code == 200
    new_id = resp.json()["id"]
    # Publish the clone, then verify a reader can switch to it and see copied content.
    await client.put(
        f"/api/v1/admin/versions/{new_id}",
        json={"is_default": False, "visibility": "published"},
    )
    _as(READER)
    tree = await client.get("/api/v1/spaces/sql-server/tree", params={"version": "2025"})
    assert tree.status_code == 200
    assert any(b["slug"] == "t-sql" for b in tree.json()["books"])  # G-04


@pytest.mark.asyncio
async def test_llm_translation_draft_then_approve(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    pid = await _page_id(session, "select")  # only has 'en'
    draft = await client.post(
        f"/api/v1/admin/pages/{pid}/translations/de/draft", json={"source_locale": "en"}
    )
    assert draft.status_code == 200
    assert draft.json()["translation_status"] == "llm_draft"  # G-07

    got = await client.get(f"/api/v1/admin/pages/{pid}/translations/de")
    assert got.json()["translation_status"] == "llm_draft"
    assert "translated" in got.json()["markdown"]  # mock translator marker

    appr = await client.post(f"/api/v1/admin/pages/{pid}/translations/de/approve")
    assert appr.json()["translation_status"] == "approved"
