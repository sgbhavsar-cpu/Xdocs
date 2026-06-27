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
ADMIN = Principal(
    sub="00000000-0000-0000-0000-0000000000ad",
    email="a@x",
    locale="en",
    roles=["admin"],
    global_permission=Permission.ADMIN,
    space_permissions={},
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
async def test_unpublish_hides_from_readers(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    pid = await _page_id(session, "select")  # a published seed page

    # Reader can read it while published.
    _as(READER)
    assert (await client.get(f"/api/v1/pages/{pid}")).status_code == 200

    # Editor unpublishes -> reverts to draft.
    _as(EDITOR)
    un = await client.post(f"/api/v1/admin/pages/{pid}/unpublish")
    assert un.status_code == 200
    assert un.json()["status"] == "draft"

    # Reader can no longer read or search it.
    _as(READER)
    assert (await client.get(f"/api/v1/pages/{pid}")).status_code == 404
    s = await client.get("/api/v1/search", params={"q": "SELECT"})
    assert all(r["page_id"] != pid for r in s.json()["results"])


@pytest.mark.asyncio
async def test_get_revision_markdown(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as(EDITOR)
    pid = await _page_id(session, "select")
    await client.put(
        f"/api/v1/admin/pages/{pid}/translations/en",
        json={"markdown": "# revision two body", "base_revision": 1},
    )
    rev = await client.get(f"/api/v1/admin/pages/{pid}/revisions/2", params={"locale": "en"})
    assert rev.status_code == 200
    assert rev.json()["markdown"] == "# revision two body"


# ---- Spaces management (create / list / edit / delete / archive) ----


@pytest.mark.asyncio
async def test_space_crud_and_archive(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    import io
    import zipfile

    client, _ = seeded_client
    _as(ADMIN)

    # Create with description + colour.
    created = await client.post(
        "/api/v1/admin/spaces",
        json={"slug": "guides", "title": "Guides", "description": "How-tos", "color": "#16a34a"},
    )
    assert created.status_code == 200
    assert created.json()["color"] == "#16a34a"

    # Appears in the management list with counts and colour.
    listed = await client.get("/api/v1/admin/spaces")
    assert listed.status_code == 200
    row = next(s for s in listed.json()["items"] if s["slug"] == "guides")
    assert row["color"] == "#16a34a"
    assert row["book_count"] == 0

    # Edit title + colour.
    upd = await client.put(
        "/api/v1/admin/spaces/guides", json={"title": "Guides V2", "color": "#0b5cad"}
    )
    assert upd.status_code == 200
    assert upd.json()["color"] == "#0b5cad"

    # Archive an existing seeded space -> a valid zip with a manifest.
    arch = await client.get("/api/v1/admin/spaces/sql-server/archive")
    assert arch.status_code == 200
    assert arch.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(arch.content))
    names = zf.namelist()
    assert "manifest.json" in names
    assert any(n.endswith(".en.md") for n in names)  # page markdown exported

    # Delete it.
    dele = await client.delete("/api/v1/admin/spaces/guides")
    assert dele.status_code == 204
    listed2 = await client.get("/api/v1/admin/spaces")
    assert all(s["slug"] != "guides" for s in listed2.json()["items"])


@pytest.mark.asyncio
async def test_editor_cannot_create_or_delete_space(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as(EDITOR)  # space WRITE but not global admin
    assert (
        await client.post("/api/v1/admin/spaces", json={"slug": "x", "title": "X"})
    ).status_code == 403
    assert (await client.delete("/api/v1/admin/spaces/sql-server")).status_code == 403
    # ...but may archive (read-only export) a space they can write.
    assert (await client.get("/api/v1/admin/spaces/sql-server/archive")).status_code == 200


def _find_page(tree: dict, page_id: str) -> dict | None:
    for b in tree["books"]:
        for p in b["pages"]:
            if p["id"] == page_id:
                return p
        for s in b["sections"]:
            for p in s["pages"]:
                if p["id"] == page_id:
                    return p
    return None


@pytest.mark.asyncio
async def test_draft_publish_two_rows(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    pid = await _page_id(session, "select")  # a published seed page

    # No pending draft initially.
    tree = (await client.get("/api/v1/admin/spaces/sql-server/tree")).json()
    assert _find_page(tree, pid)["has_draft"] is False

    # Reader sees the published content.
    _as(READER)
    before = (await client.get(f"/api/v1/pages/{pid}")).json()["html"]
    assert "DRAFTONLY" not in before

    # Editor edits and saves a draft (published copy stays live).
    _as(EDITOR)
    await client.put(
        f"/api/v1/admin/pages/{pid}/translations/en",
        json={"markdown": "# SELECT\n\nDRAFTONLY body"},
    )
    tree = (await client.get("/api/v1/admin/spaces/sql-server/tree")).json()
    assert _find_page(tree, pid)["has_draft"] is True  # second "Draft" row appears
    got = (await client.get(f"/api/v1/admin/pages/{pid}/translations/en")).json()
    assert got["has_draft"] is True
    assert "DRAFTONLY" in got["markdown"]
    assert "DRAFTONLY" not in got["published_markdown"]  # published snapshot unchanged

    # Reader still sees the old published content.
    _as(READER)
    assert "DRAFTONLY" not in (await client.get(f"/api/v1/pages/{pid}")).json()["html"]

    # Publishing the draft replaces the live version; rows merge.
    _as(EDITOR)
    await client.post(f"/api/v1/admin/pages/{pid}/publish")
    tree = (await client.get("/api/v1/admin/spaces/sql-server/tree")).json()
    assert _find_page(tree, pid)["has_draft"] is False
    _as(READER)
    assert "DRAFTONLY" in (await client.get(f"/api/v1/pages/{pid}")).json()["html"]


@pytest.mark.asyncio
async def test_discard_draft_reverts(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    pid = await _page_id(session, "select")
    published = (await client.get(f"/api/v1/admin/pages/{pid}/translations/en")).json()[
        "published_markdown"
    ]

    await client.put(
        f"/api/v1/admin/pages/{pid}/translations/en",
        json={"markdown": "# SELECT\n\nthrowaway edit"},
    )
    assert (await client.get(f"/api/v1/admin/pages/{pid}/translations/en")).json()["has_draft"]

    resp = await client.post(f"/api/v1/admin/pages/{pid}/discard-draft", params={"locale": "en"})
    assert resp.status_code == 200
    after = (await client.get(f"/api/v1/admin/pages/{pid}/translations/en")).json()
    assert after["has_draft"] is False
    assert after["markdown"] == published  # working copy reverted to the published version


# ---- Books in a space (add / archive) ----


@pytest.mark.asyncio
async def test_add_book_to_space_and_archive(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    import io
    import zipfile

    client, _ = seeded_client
    _as(EDITOR)

    # Add a book to the space (default version + slug resolved server-side).
    created = await client.post(
        "/api/v1/admin/spaces/sql-server/books", json={"title": "Operations Guide"}
    )
    assert created.status_code == 200
    book = created.json()
    assert book["slug"] == "operations-guide"

    # It shows up in the space tree.
    tree = (await client.get("/api/v1/admin/spaces/sql-server/tree")).json()
    assert any(b["id"] == book["id"] for b in tree["books"])

    # Archive a seeded book -> a valid zip with a manifest scoped to that book.
    tsql = next(b for b in tree["books"] if b["slug"] == "t-sql")["id"]
    arch = await client.get(f"/api/v1/admin/books/{tsql}/archive")
    assert arch.status_code == 200
    assert arch.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(arch.content))
    assert "manifest.json" in zf.namelist()


# ---- Sections + page rename (side menu) ----


@pytest.mark.asyncio
async def test_sections_and_page_rename(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as(EDITOR)
    bid = await _book_id(session, "t-sql")

    # Create a section.
    sec = await client.post(
        "/api/v1/admin/sections", json={"book_id": bid, "title": "Statements"}
    )
    assert sec.status_code == 200
    section_id = sec.json()["id"]

    # Create a page inside it.
    page = await client.post(
        "/api/v1/admin/pages",
        json={"book_id": bid, "slug": "delete", "title": "DELETE", "section_id": section_id},
    )
    assert page.status_code == 200
    page_id = page.json()["id"]

    # The admin tree groups it under the section.
    tree = await client.get("/api/v1/admin/spaces/sql-server/tree")
    book = next(b for b in tree.json()["books"] if b["id"] == bid)
    section = next(s for s in book["sections"] if s["id"] == section_id)
    assert any(p["id"] == page_id for p in section["pages"])

    # Rename the page (translation title).
    ren = await client.put(
        f"/api/v1/admin/pages/{page_id}", json={"title": "DELETE statement", "locale": "en"}
    )
    assert ren.status_code == 200
    got = await client.get(f"/api/v1/admin/pages/{page_id}/translations/en")
    assert got.json()["title"] == "DELETE statement"

    # Rename the section.
    assert (
        await client.put(f"/api/v1/admin/sections/{section_id}", json={"title": "DML"})
    ).status_code == 200

    # Delete the section -> ungroups the page (kept, section_id cleared).
    assert (await client.delete(f"/api/v1/admin/sections/{section_id}")).status_code == 204
    tree2 = await client.get("/api/v1/admin/spaces/sql-server/tree")
    book2 = next(b for b in tree2.json()["books"] if b["id"] == bid)
    assert all(s["id"] != section_id for s in book2["sections"])
    assert any(p["id"] == page_id for p in book2["pages"])  # now top-level


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
