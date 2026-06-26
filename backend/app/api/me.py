"""Authenticated identity endpoint — proves the host-issued-token flow end to end.

Returns the resolved principal and the spaces the caller can read. Used by the
test host (mock-IdP) to validate JWT + JWKS + permission mapping (story A6).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.deps import CurrentUser

router = APIRouter(tags=["auth"])


class MeResponse(BaseModel):
    sub: str
    email: str | None
    locale: str | None
    roles: list[str]
    global_permission: str | None
    space_permissions: dict[str, str]


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser) -> MeResponse:
    return MeResponse(
        sub=user.sub,
        email=user.email,
        locale=user.locale,
        roles=user.roles,
        global_permission=user.global_permission.name.lower() if user.global_permission else None,
        space_permissions={k: v.name.lower() for k, v in user.space_permissions.items()},
    )
