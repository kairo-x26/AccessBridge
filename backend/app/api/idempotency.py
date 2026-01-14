"""Idempotency-Key support for mutations (NFR reliability: idempotent mutations)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.models import IdempotencyRecord


def body_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(jsonable_encoder(payload), sort_keys=True, default=str).encode()
    ).hexdigest()


def run_idempotent(
    session: Session,
    *,
    organization_id: str,
    key: str | None,
    endpoint: str,
    request_hash: str,
    status_code: int,
    compute: Callable[[], Any],
) -> JSONResponse:
    if key:
        prior = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.key == key,
                IdempotencyRecord.endpoint == endpoint,
            )
        )
        if prior:
            if prior.request_hash != request_hash:
                raise Conflict("This Idempotency-Key was already used with a different request.")
            return JSONResponse(
                prior.response, status_code=prior.status_code, headers={"idempotent-replay": "true"}
            )
    body = jsonable_encoder(compute())
    if key:
        session.add(
            IdempotencyRecord(
                organization_id=organization_id,
                key=key[:120],
                endpoint=endpoint,
                request_hash=request_hash,
                status_code=status_code,
                response=body,
            )
        )
        session.flush()
    return JSONResponse(body, status_code=status_code)
