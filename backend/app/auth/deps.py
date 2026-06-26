"""FastAPI auth dependencies: extract & validate the bearer token, build a Principal."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.auth.jwt import TokenVerifier
from app.auth.permissions import Permission, Principal, principal_from_claims
from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError

_verifier: TokenVerifier | None = None


def get_verifier(settings: Annotated[Settings, Depends(get_settings)]) -> TokenVerifier:
    """Lazily build a process-wide verifier from settings (overridable in tests)."""
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier(
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            algorithms=settings.algorithms,
            jwks_url=settings.jwks_url,
        )
    return _verifier


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError("Missing or malformed Authorization header.")
    return token


def get_current_user(
    request: Request,
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> Principal:
    claims = verifier.verify(_bearer_token(request))
    return principal_from_claims(claims)


CurrentUser = Annotated[Principal, Depends(get_current_user)]


def require_space_permission(required: Permission) -> Callable[..., Principal]:
    """Dependency factory enforcing a permission on the `space` path/query param."""

    def _dep(request: Request, user: CurrentUser) -> Principal:
        space = request.path_params.get("space") or request.query_params.get("space")
        if space and not user.can(space, required):
            raise ForbiddenError(
                "Insufficient permission for this space.", details={"space": space}
            )
        return user

    return _dep
