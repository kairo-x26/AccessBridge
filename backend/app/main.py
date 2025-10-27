"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api
from app.core import db
from app.core.config import get_settings
from app.core.errors import install_handlers
from app.core.logging import request_id_var, setup_logging


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="AccessBridge AI",
        version="0.1.0",
        description="Administrative coordination of outpatient specialist referrals.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = rid
        response.headers["server-timing"] = f"app;dur={(time.perf_counter() - start) * 1000:.1f}"
        return response

    install_handlers(app)
    app.include_router(api)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        with db.engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"status": "ok"}

    return app


app = create_app()
