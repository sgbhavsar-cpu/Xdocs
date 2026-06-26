"""Search response schemas (API Spec §5)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class SearchResult(BaseModel):
    page_id: uuid.UUID
    title: str
    space: str
    book_id: uuid.UUID
    locale: str
    best_anchor: str | None
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    scope: str
    results: list[SearchResult]
    next_cursor: str | None = None


class Suggestion(BaseModel):
    page_id: uuid.UUID
    title: str
    space: str


class SuggestResponse(BaseModel):
    items: list[Suggestion]
