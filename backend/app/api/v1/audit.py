from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import DB, Principal, require
from app.core.tenancy import scoped
from app.domain.rbac import Perm
from app.models import AuditEvent

router = APIRouter(prefix="/audit-events", tags=["audit"])
Auditor = Annotated[Principal, Depends(require(Perm.AUDIT_READ))]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor: str
    operation: str
    resource_ref: str | None
    outcome: str
    details: dict[str, Any]
    request_id: str | None
    timestamp: datetime


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_before: datetime | None


@router.get("", response_model=AuditPage)
def list_audit(
    principal: Auditor,
    session: DB,
    operation: str | None = None,
    resource_ref: str | None = None,
    actor: str | None = None,
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> AuditPage:
    q = scoped(AuditEvent, principal.organization_id)
    if operation:
        q = q.where(AuditEvent.operation.startswith(operation))
    if resource_ref:
        q = q.where(AuditEvent.resource_ref == resource_ref)
    if actor:
        q = q.where(AuditEvent.actor == actor)
    if before:
        q = q.where(AuditEvent.timestamp < before)
    rows = list(session.scalars(q.order_by(AuditEvent.timestamp.desc()).limit(limit + 1)))
    more = len(rows) > limit
    items = rows[:limit]
    return AuditPage(
        items=[AuditOut.model_validate(r) for r in items],
        next_before=items[-1].timestamp if more and items else None,
    )
