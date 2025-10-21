"""Audit trail writer (FR-18). Callers pass references, never PHI values."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import _scrub, request_id_var
from app.models import AuditEvent


def record(
    session: Session,
    *,
    organization_id: str | None,
    actor: str,
    operation: str,
    resource_ref: str | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=organization_id,
        actor=actor,
        operation=operation,
        resource_ref=resource_ref,
        outcome=outcome,
        details=_scrub(details or {}),
        request_id=request_id_var.get(),
    )
    session.add(event)
    session.flush()
    return event
