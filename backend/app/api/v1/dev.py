"""Development-only simulators for the demo: patient replies, carrier receipts and specialist
system updates. Not mounted in production."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import DB, Principal, require
from app.core.db import new_id
from app.domain.rbac import Perm
from app.integrations import fhir, sms
from app.models import Organization
from app.services import messaging, reconciliation

router = APIRouter(prefix="/dev/simulate", tags=["dev"])
Staff = Annotated[Principal, Depends(require(Perm.REFERRAL_READ))]


class ReplyIn(BaseModel):
    phone: str = Field(max_length=30)
    body: str = Field(max_length=1000)


@router.post("/patient-reply")
def patient_reply(body: ReplyIn, principal: Staff, session: DB) -> dict[str, str]:
    org = session.get(Organization, principal.organization_id)
    assert org is not None
    payload: dict[str, Any] = {
        "type": "inbound",
        "event_id": new_id("sim"),
        "account": org.slug,
        "from": body.phone,
        "body": body.body,
    }
    return {"result": messaging.handle_inbound(session, payload)}


class DeliveryIn(BaseModel):
    message_id: str
    status: Literal["delivered", "failed"] = "delivered"


@router.post("/delivery")
def delivery(body: DeliveryIn, principal: Staff, session: DB) -> dict[str, str]:
    payload = {"type": "delivery", "event_id": new_id("sim"), **body.model_dump()}
    return {"result": messaging.handle_delivery(session, payload)}


class SpecialistUpdateIn(BaseModel):
    service_request_id: str
    status: Literal["accepted", "in-progress", "completed", "rejected", "cancelled"]
    appointment: str | None = None
    report_reference: str | None = None


@router.post("/specialist-update")
def specialist_update(body: SpecialistUpdateIn, principal: Staff, session: DB) -> dict[str, Any]:
    from app.integrations import simulated_ehr

    res = simulated_ehr.task_update(
        body.service_request_id,
        body.status,
        version=int(new_id("v")[-6:], 16),
        appointment=body.appointment,
        report_reference=body.report_reference,
    )
    r = reconciliation.reconcile_task(session, principal.organization_id, fhir.parse_task(res))
    return {"outcome": r.outcome, "applied": r.applied, "detail": r.detail}


@router.get("/outbox")
def outbox(principal: Staff) -> list[dict[str, str]]:
    """Messages the simulated SMS gateway 'sent' (the demo's stand-in for a phone)."""
    return list(reversed(sms.gateway.outbox[-50:]))
