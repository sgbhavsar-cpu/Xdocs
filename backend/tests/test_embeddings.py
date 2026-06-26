"""Embedding provider tests (C2)."""

from __future__ import annotations

import pytest

from app.llm.embeddings import MockEmbeddingProvider, cosine


@pytest.mark.asyncio
async def test_deterministic() -> None:
    p = MockEmbeddingProvider()
    a = await p.embed(["select into creates a table"])
    b = await p.embed(["select into creates a table"])
    assert a == b


@pytest.mark.asyncio
async def test_similar_text_has_higher_cosine() -> None:
    p = MockEmbeddingProvider()
    vecs = await p.embed(
        [
            "create a new table from a query result using select into",
            "select into makes a table from a query",
            "bananas oranges and apples are fruit",
        ]
    )
    related = cosine(vecs[0], vecs[1])
    unrelated = cosine(vecs[0], vecs[2])
    assert related > unrelated


def test_cosine_edge_cases() -> None:
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
