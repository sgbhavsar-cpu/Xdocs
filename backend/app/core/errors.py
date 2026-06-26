"""Unified error handling producing the API error envelope (API Spec §1.1)."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()


class XdocsError(Exception):
    """Base application error mapped to the standard envelope."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(XdocsError):
    status_code = 404
    code = "not_found"


class UnauthorizedError(XdocsError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(XdocsError):
    status_code = 403
    code = "forbidden"


class ConflictError(XdocsError):
    status_code = 409
    code = "conflict"


class RateLimitedError(XdocsError):
    status_code = 429
    code = "rate_limited"


class BudgetExceededError(XdocsError):
    status_code = 429
    code = "budget_exceeded"


def _envelope(
    *, code: str, message: str, request_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details or {},
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(XdocsError)
    async def _xdocs(request: Request, exc: XdocsError) -> JSONResponse:
        rid = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                code=exc.code, message=exc.message, request_id=rid, details=exc.details
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        rid = getattr(request.state, "request_id", "")
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code=code, message=str(exc.detail), request_id=rid),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        rid = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=422,
            content=_envelope(
                code="validation_error",
                message="Request validation failed.",
                request_id=rid,
                details={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = getattr(request.state, "request_id", "")
        log.error("unhandled_exception", error=str(exc), request_id=rid)
        return JSONResponse(
            status_code=500,
            content=_envelope(
                code="internal_error", message="Internal server error.", request_id=rid
            ),
        )
