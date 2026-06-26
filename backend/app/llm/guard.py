"""Rate limiting and budget guard for LLM endpoints (D1, design §6.4).

In-process implementation (sliding window + token counter) suitable for the
target scale; swap the store for Redis to share limits across replicas.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.core.errors import BudgetExceededError, RateLimitedError


class LlmGuard:
    def __init__(self, *, rate_per_min: int, token_budget: int) -> None:
        self.rate_per_min = rate_per_min
        self.token_budget = token_budget
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._spent = 0

    def check_rate(self, sub: str) -> None:
        now = time.monotonic()
        dq = self._events[sub]
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= self.rate_per_min:
            raise RateLimitedError("LLM rate limit exceeded. Try again shortly.")
        dq.append(now)

    def check_budget(self, estimated_tokens: int) -> None:
        if self._spent + estimated_tokens > self.token_budget:
            raise BudgetExceededError("Monthly LLM token budget exhausted.")

    def record(self, tokens: int) -> None:
        self._spent += tokens


_guard: LlmGuard | None = None


def get_llm_guard(settings: Annotated[Settings, Depends(get_settings)]) -> LlmGuard:
    global _guard
    if _guard is None:
        _guard = LlmGuard(
            rate_per_min=settings.llm_rate_limit_per_min,
            token_budget=settings.llm_monthly_token_budget,
        )
    return _guard
