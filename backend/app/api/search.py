"""Search endpoints (API Spec §5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.db import get_session
from app.search import service
from app.search.schemas import SearchResponse, SuggestResponse

router = APIRouter(tags=["search"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/search", response_model=SearchResponse)
async def search(
    session: Session,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1)],
    scope: Annotated[str, Query()] = "corpus",
    locale: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    results = await service.search(session, user, q=q, scope=scope, locale=locale, limit=limit)
    return SearchResponse.model_validate({"query": q, "scope": scope, "results": results})


@router.get("/search/suggest", response_model=SuggestResponse)
async def suggest(
    session: Session,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=1)],
    scope: Annotated[str, Query()] = "corpus",
) -> SuggestResponse:
    items = await service.suggest(session, user, q=q, scope=scope)
    return SuggestResponse.model_validate({"items": items})
