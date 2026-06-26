"""Liveness and readiness endpoints (API Spec §2). Unauthenticated."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, object]:
    checks: dict[str, str] = {}
    status = "ok"
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        checks["database"] = "unavailable"
        status = "degraded"
    return {"status": status, "checks": checks}
