"""Embedding providers (C2).

A small abstraction so the indexer and search share one embedder. The default
`mock` provider is deterministic and offline (feature-hashed bag-of-words, L2
normalized) — it gives sensible cosine similarity for tests and local dev. The
OpenAI/Azure provider uses `text-embedding-3-small` (design §16.2).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from app.core.config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MOCK_DIM = 256


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class MockEmbeddingProvider:
    """Deterministic, offline embeddings via feature hashing."""

    def __init__(self, dim: int = _MOCK_DIM) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)  # noqa: S324 (non-crypto use)
            v[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAIEmbeddingProvider:
    """Real embeddings via OpenAI/Azure (used when LLM_PROVIDER != mock)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        return [item["embedding"] for item in data]


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.llm_provider in ("openai", "azure") and settings.openai_api_key:
        return OpenAIEmbeddingProvider(settings.openai_api_key, settings.llm_embed_model)
    return MockEmbeddingProvider()


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Vectors from the same provider; mock vectors are
    pre-normalized so this reduces to a dot product."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
