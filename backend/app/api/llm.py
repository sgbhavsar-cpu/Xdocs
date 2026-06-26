"""LLM endpoints: Ask (SSE), summarize, extract, translate, feedback (API Spec §6)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.db import get_session
from app.llm import service
from app.llm.chat import estimate_tokens
from app.llm.guard import LlmGuard, get_llm_guard
from app.llm.schemas import (
    ArtifactOut,
    AskRequest,
    ExtractRequest,
    FeedbackRequest,
    SummarizeRequest,
    TranslateOut,
    TranslateRequest,
)

router = APIRouter(tags=["llm"], prefix="/llm")

Session = Annotated[AsyncSession, Depends(get_session)]
Guard = Annotated[LlmGuard, Depends(get_llm_guard)]


@router.post("/ask")
async def ask(req: AskRequest, session: Session, user: CurrentUser, guard: Guard) -> Response:
    # Guard checks happen before streaming so we can return a 429 cleanly.
    guard.check_rate(user.sub)
    guard.check_budget(estimate_tokens(req.question))
    stream = service.ask_stream(
        session, user, guard, question=req.question, scope=req.scope, locale=req.locale
    )
    return StreamingResponse(stream, media_type="text/event-stream")


@router.post("/summarize", response_model=ArtifactOut)
async def summarize(
    req: SummarizeRequest, session: Session, user: CurrentUser, guard: Guard
) -> ArtifactOut:
    guard.check_rate(user.sub)
    artifact = await service.summarize(
        session, user, guard, target=req.target.model_dump(), style=req.style, locale=req.locale
    )
    return ArtifactOut.model_validate(artifact)


@router.post("/extract", response_model=ArtifactOut)
async def extract(
    req: ExtractRequest, session: Session, user: CurrentUser, guard: Guard
) -> ArtifactOut:
    guard.check_rate(user.sub)
    artifact = await service.extract(
        session,
        user,
        guard,
        instruction=req.instruction,
        scope=req.scope,
        locale=req.locale,
        fmt=req.format,
    )
    return ArtifactOut.model_validate(artifact)


@router.post("/translate", response_model=TranslateOut)
async def translate(
    req: TranslateRequest, session: Session, user: CurrentUser, guard: Guard
) -> TranslateOut:
    guard.check_rate(user.sub)
    result = await service.translate(
        session,
        user,
        guard,
        page_id=req.page_id,
        target_locale=req.target_locale,
        source_locale=req.source_locale,
    )
    return TranslateOut.model_validate(result)


@router.post("/feedback", status_code=204)
async def feedback(req: FeedbackRequest, session: Session, user: CurrentUser) -> Response:
    await service.record_feedback(
        session, user, answer_id=req.answer_id, rating=req.rating, comment=req.comment
    )
    return Response(status_code=204)


@router.get("/artifacts/{artifact_id}/md", response_class=PlainTextResponse)
async def artifact_md(artifact_id: uuid.UUID, session: Session, user: CurrentUser) -> str:
    return await service.get_artifact_markdown(session, artifact_id)
