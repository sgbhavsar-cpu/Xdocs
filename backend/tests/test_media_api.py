"""Media upload/serve tests (F5: F-09, F-10)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.main import app

EDITOR = Principal(
    sub="00000000-0000-0000-0000-0000000000ee",
    email="e@x",
    locale="en",
    roles=[],
    global_permission=None,
    space_permissions={"sql-server": Permission.WRITE},
)

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _as(user: Principal = EDITOR) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.mark.asyncio
async def test_upload_and_serve(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as()
    resp = await client.post(
        "/api/v1/media",
        files={"file": ("logo.png", _PNG, "image/png")},
        data={"space": "sql-server"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_type"] == "image/png"
    served = await client.get(body["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == _PNG


@pytest.mark.asyncio
async def test_reject_disallowed_type(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as()
    resp = await client.post(
        "/api/v1/media",
        files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
        data={"space": "sql-server"},
    )
    assert resp.status_code == 422  # F-10
