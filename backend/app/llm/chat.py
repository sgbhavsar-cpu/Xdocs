"""Chat providers for RAG / summarize / extract / translate (D1).

The default `mock` provider is deterministic and offline: its output is derived
from the prompt so tests can assert behavior without network or cost. The OpenAI/
Azure provider streams real completions (design §16.2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.core.config import get_settings


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _first_sentences(text: str, n: int) -> str:
    parts = [p.strip() for p in text.replace("\n", " ").split(".") if p.strip()]
    return ". ".join(parts[:n]).strip() + ("." if parts else "")


class ChatProvider(Protocol):
    # An async-generator method: a plain `def` returning an AsyncIterator (not a
    # coroutine), matching the `async def ... yield` implementations.
    def stream(self, system: str, user: str) -> AsyncIterator[str]: ...
    async def complete(self, system: str, user: str) -> str: ...


class MockChatProvider:
    """Deterministic, offline chat. Output depends on the task hint in `system`."""

    def _respond(self, system: str, user: str) -> str:
        s = system.lower()
        if "summar" in s:
            return f"## Summary\n\n{_first_sentences(user, 2)}"
        if "extract" in s:
            return f"| Item | Value |\n| --- | --- |\n| sample | {' '.join(user.split()[:3])} |"
        if "translat" in s:
            return f"[translated] {user}"
        # RAG answer, grounded in the provided context.
        return f"Based on the documentation: {_first_sentences(user, 1)}"

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        for word in self._respond(system, user).split(" "):
            yield word + " "

    async def complete(self, system: str, user: str) -> str:
        return self._respond(system, user)


class OpenAIChatProvider:
    """Streaming chat via OpenAI/Azure (used when LLM_PROVIDER != mock)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        import json

        import httpx

        payload = {
            "model": self.model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                    if delta:
                        yield delta

    async def complete(self, system: str, user: str) -> str:
        return "".join([tok async for tok in self.stream(system, user)])


def get_chat_provider() -> ChatProvider:
    settings = get_settings()
    if settings.llm_provider in ("openai", "azure") and settings.openai_api_key:
        return OpenAIChatProvider(settings.openai_api_key, settings.llm_chat_model)
    return MockChatProvider()
