"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, analytics, content, export, health, llm, me, media, search
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="Xdocs API",
        version="0.0.1",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["ETag"],
    )

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-ID", uuid.uuid4().hex)
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        # Baseline security headers (H4). CSP/frame policy are left to the host,
        # since the control is designed to be embedded.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    register_error_handlers(app)

    base = settings.api_base_path
    # Health is exposed at the root for infra probes (API Spec §2).
    app.include_router(health.router)
    app.include_router(me.router, prefix=base)
    app.include_router(content.router, prefix=base)
    app.include_router(search.router, prefix=base)
    app.include_router(llm.router, prefix=base)
    app.include_router(export.router, prefix=base)
    app.include_router(admin.router, prefix=base)
    app.include_router(media.router, prefix=base)
    app.include_router(analytics.router, prefix=base)

    return app


app = create_app()
