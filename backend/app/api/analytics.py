"""Analytics endpoints (API Spec §9.5, design §10)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import service
from app.auth.deps import CurrentUser
from app.core.db import get_session

router = APIRouter(tags=["analytics"])

Session = Annotated[AsyncSession, Depends(get_session)]


class PageViewReq(BaseModel):
    page_id: uuid.UUID


@router.post("/analytics/pageview", status_code=204)
async def pageview(req: PageViewReq, session: Session, user: CurrentUser) -> None:
    await service.record_pageview(session, user, req.page_id)


@router.get("/admin/analytics/pageviews")
async def pageviews(
    session: Session,
    user: CurrentUser,
    space: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    return {"items": await service.popular_pages(session, user, space=space, limit=limit)}


@router.get("/admin/analytics/llm-feedback")
async def llm_feedback(session: Session, user: CurrentUser) -> dict[str, Any]:
    return await service.feedback_summary(session, user)
