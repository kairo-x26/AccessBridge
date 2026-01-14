from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import DB, Principal, require
from app.core.errors import ValidationFailed
from app.core.tenancy import scoped
from app.domain.rbac import Perm
from app.integrations import fhir
from app.models import IntegrationEvent
from app.services import reconciliation

router = APIRouter(prefix="/integrations", tags=["integrations"])
# Inbound integration traffic is accepted from staff able to import or from the integration
# service account (an admin-provisioned coordinator-role identity in the MVP).
Importer = Annotated[Principal, Depends(require(Perm.REFERRAL_IMPORT))]
Viewer = Annotated[Principal, Depends(require(Perm.REFERRAL_READ))]


class TaskUpdatesIn(BaseModel):
    resources: list[dict[str, Any]]


class ReconcileOut(BaseModel):
    external_id: str | None
    outcome: str
    referral_id: str | None
    detail: str
    applied: list[str]


@router.post("/fhir/task-updates", response_model=list[ReconcileOut])
def fhir_task_updates(body: TaskUpdatesIn, principal: Importer, session: DB) -> list[ReconcileOut]:
    if len(body.resources) > 500:
        raise ValidationFailed("Send at most 500 Task resources per request.")
    out = []
    for res in body.resources:
        try:
            upd = fhir.parse_task(res)
        except fhir.FhirParseError as exc:
            out.append(
                ReconcileOut(
                    external_id=None,
                    outcome="invalid",
                    referral_id=None,
                    detail=str(exc),
                    applied=[],
                )
            )
            continue
        r = reconciliation.reconcile_task_safely(session, principal.organization_id, upd)
        out.append(
            ReconcileOut(
                external_id=upd.external_id,
                outcome=r.outcome,
                referral_id=r.referral_id,
                detail=r.detail,
                applied=r.applied,
            )
        )
    return out


class IntegrationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    external_id: str
    kind: str
    referral_id: str | None
    outcome: str
    detail: str | None
    received_at: datetime


@router.get("/events", response_model=list[IntegrationEventOut])
def list_events(
    principal: Viewer, session: DB, referral_id: str | None = None, limit: int = Query(100, le=500)
) -> list[IntegrationEvent]:
    q = scoped(IntegrationEvent, principal.organization_id)
    if referral_id:
        q = q.where(IntegrationEvent.referral_id == referral_id)
    return list(session.scalars(q.order_by(IntegrationEvent.received_at.desc()).limit(limit)))
