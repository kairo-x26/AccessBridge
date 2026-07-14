"""FastAPI application factory."""

from __future__ import annotations

import hmac
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select

from app.api.router import api, dev_api
from app.core import db
from app.core.config import get_settings
from app.core.errors import Unauthorized, install_handlers
from app.core.logging import request_id_var, setup_logging
from app.core.metrics import registry
from app.services import notifications  # noqa: F401  (registers transition hooks)

MAX_BODY_BYTES = 12 * 1024 * 1024
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "cache-control": "no-store",
}


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="AccessBridge AI",
        version="1.0.0",
        description="Administrative coordination of outpatient specialist referrals.",
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["authorization", "content-type", "idempotency-key", "x-request-id"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        rid = rid[:64]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
                response: Response = JSONResponse(
                    {
                        "error": {
                            "code": "too_large",
                            "message": "Request is larger than 12 MB.",
                            "details": {},
                        }
                    },
                    status_code=413,
                )
            else:
                response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        registry.observe(
            request.method, getattr(route, "path", "unmatched"), response.status_code, elapsed
        )
        response.headers["x-request-id"] = rid
        response.headers["server-timing"] = f"app;dur={elapsed * 1000:.1f}"
        for k, v in SECURITY_HEADERS.items():
            if k == "cache-control" and k in response.headers:
                continue
            if k == "content-security-policy" and request.url.path == "/docs":
                continue
            response.headers.setdefault(k, v)
        if settings.environment == "production":
            response.headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        return response

    install_handlers(app)
    app.include_router(api)
    if settings.environment != "production":
        app.include_router(dev_api)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        with db.engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"status": "ok"}

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def metrics(authorization: str | None = Header(default=None)) -> PlainTextResponse:
        """Prometheus metrics: aggregate counts only, never patient data."""
        expected = settings.metrics_token
        if expected:
            supplied = (authorization or "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(supplied, expected):
                raise Unauthorized("Metrics need the scrape token.")
        elif settings.environment == "production":
            raise Unauthorized("Set AB_METRICS_TOKEN to expose metrics.")
        from app.models import AgentAction, Job, Referral

        with db.session_factory()() as s:
            jobs = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
            refs = dict(
                s.execute(select(Referral.status, func.count()).group_by(Referral.status)).all()
            )
            decisions = dict(
                s.execute(
                    select(AgentAction.decision, func.count()).group_by(AgentAction.decision)
                ).all()
            )
        gauges = {
            "accessbridge_jobs": {(("status", k),): v for k, v in jobs.items()},
            "accessbridge_referrals": {(("status", k),): v for k, v in refs.items()},
            "accessbridge_agent_actions": {(("decision", k),): v for k, v in decisions.items()},
        }
        return PlainTextResponse(registry.render(gauges), media_type="text/plain; version=0.0.4")

    return app


app = create_app()
