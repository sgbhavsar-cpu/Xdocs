"""Export endpoints (API Spec §7)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.core.db import get_session
from app.export import service
from app.export.schemas import ExportJobOut, ExportRequest

router = APIRouter(tags=["export"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/export", response_model=ExportJobOut)
async def create_export(req: ExportRequest, session: Session, user: CurrentUser) -> ExportJobOut:
    job = await service.create_and_render(
        session, user, scope_type=req.scope.type, scope_id=req.scope.id, locale=req.locale
    )
    return ExportJobOut.model_validate(service.job_summary(job))


@router.get("/export/{job_id}", response_model=ExportJobOut)
async def export_status(job_id: uuid.UUID, session: Session, user: CurrentUser) -> ExportJobOut:
    job = await service.get_job(session, job_id)
    return ExportJobOut.model_validate(service.job_summary(job))


@router.get("/export/{job_id}/download")
async def export_download(job_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    pdf = await service.get_pdf(session, job_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="xdocs-{job_id}.pdf"'},
    )
