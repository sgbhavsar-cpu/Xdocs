"""LLM API tests (D2, D4, D5, D6 + guard): D-02..D-15."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.permissions import Permission, Principal
from app.llm.guard import LlmGuard, get_llm_guard
from app.main import app
from app.models.content import Page

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


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event:
            events.append((event, data))
    return events


async def _page_id(session: AsyncSession, slug: str) -> str:
    page = (await session.execute(select(Page).where(Page.slug == slug))).scalar_one()
    return str(page.id)


@pytest.mark.asyncio
async def test_ask_streams_answer_with_citations(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as()
    resp = await client.post("/api/v1/llm/ask", json={"question": "select into", "scope": "corpus"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    types = [e[0] for e in events]
    assert types[0] == "token"
    assert "citations" in types
    assert types[-1] == "done"
    citations = next(d for t, d in events if t == "citations")
    assert citations["items"]  # grounded, has sources (D-04)


@pytest.mark.asyncio
async def test_ask_not_covered(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as()
    resp = await client.post(
        "/api/v1/llm/ask", json={"question": "zzzqqq totally unrelated", "scope": "corpus"}
    )
    events = _parse_sse(resp.text)
    citations = next(d for t, d in events if t == "citations")
    assert citations["items"] == []  # D-05
    answer = "".join(d["text"] for t, d in events if t == "token")
    assert "couldn't find" in answer.lower()


@pytest.mark.asyncio
async def test_ask_acl_scoped(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as()  # reader cannot read platform
    resp = await client.post(
        "/api/v1/llm/ask", json={"question": "platform overview", "scope": "corpus"}
    )
    events = _parse_sse(resp.text)
    citations = next(d for t, d in events if t == "citations")
    titles = [c["title"] for c in citations["items"]]
    assert "Platform Overview" not in titles  # platform content not retrievable by reader


@pytest.mark.asyncio
async def test_summarize_creates_downloadable_artifact(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, session = seeded_client
    _as()
    pid = await _page_id(session, "select")
    resp = await client.post("/api/v1/llm/summarize", json={"target": {"type": "page", "id": pid}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "summary"
    assert body["markdown"].startswith("## Summary")
    dl = await client.get(body["download"]["md"])
    assert dl.status_code == 200
    assert dl.text == body["markdown"]


@pytest.mark.asyncio
async def test_extract_artifact(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as()
    resp = await client.post(
        "/api/v1/llm/extract",
        json={"instruction": "list the arguments", "scope": "space:sql-server"},
    )
    assert resp.status_code == 200
    assert "| Item |" in resp.json()["markdown"]


@pytest.mark.asyncio
async def test_translate_caches(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, session = seeded_client
    _as()
    pid = await _page_id(session, "getting-started")
    first = await client.post("/api/v1/llm/translate", json={"page_id": pid, "target_locale": "de"})
    assert first.status_code == 200
    assert first.json()["cached"] is False
    assert "translated" in first.json()["html"]
    second = await client.post(
        "/api/v1/llm/translate", json={"page_id": pid, "target_locale": "de"}
    )
    assert second.json()["cached"] is True


@pytest.mark.asyncio
async def test_feedback(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as()
    resp = await client.post(
        "/api/v1/llm/feedback",
        json={"answer_id": "11111111-1111-1111-1111-111111111111", "rating": "up"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_rate_limit_returns_429(seeded_client: tuple[AsyncClient, AsyncSession]) -> None:
    client, _ = seeded_client
    _as()
    app.dependency_overrides[get_llm_guard] = lambda: LlmGuard(rate_per_min=0, token_budget=10**9)
    resp = await client.post("/api/v1/llm/ask", json={"question": "anything"})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_budget_exceeded_returns_429(
    seeded_client: tuple[AsyncClient, AsyncSession],
) -> None:
    client, _ = seeded_client
    _as()
    app.dependency_overrides[get_llm_guard] = lambda: LlmGuard(rate_per_min=1000, token_budget=0)
    resp = await client.post("/api/v1/llm/ask", json={"question": "anything"})
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "budget_exceeded"
