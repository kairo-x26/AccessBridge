"""Patient communication, templates, contact preferences, webhooks and notifications."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.api.deps import DB, Principal, require
from app.core.db import new_id, utcnow
from app.core.errors import (
    Conflict,
    Forbidden,
    ServiceUnavailable,
    Unauthorized,
    ValidationFailed,
)
from app.core.ratelimit import client_ip, limit
from app.core.tenancy import get_scoped, scoped
from app.domain import templates as tpl_rules
from app.domain.rbac import Perm
from app.integrations import sms
from app.models import Communication, MessageTemplate, Notification, PatientReference, Referral
from app.services import audit, messaging

router = APIRouter(tags=["communications"])
Reader = Annotated[Principal, Depends(require(Perm.MESSAGE_READ))]
Sender = Annotated[Principal, Depends(require(Perm.MESSAGE_SEND))]
TemplateAdmin = Annotated[Principal, Depends(require(Perm.TEMPLATE_MANAGE))]
AnyStaff = Annotated[Principal, Depends(require())]


class CommunicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    referral_id: str | None
    direction: str
    channel: str
    template_key: str | None
    language: str | None
    body: str | None
    status: str
    failure_reason: str | None
    classification: str | None
    classified_by: str | None
    escalated: bool
    resolved_at: datetime | None
    in_reply_to: str | None
    action_id: str | None
    created_by: str
    created_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None


@router.get("/referrals/{referral_id}/communications", response_model=list[CommunicationOut])
def referral_messages(referral_id: str, principal: Reader, session: DB) -> list[Communication]:
    get_scoped(session, Referral, referral_id, principal.organization_id)
    return list(
        session.scalars(
            select(Communication)
            .where(Communication.referral_id == referral_id)
            .order_by(Communication.created_at)
        )
    )


class PreviewOut(BaseModel):
    can_send: bool
    problems: list[str]
    body: str | None
    language: str | None


class SendIn(BaseModel):
    template_key: str


@router.post("/referrals/{referral_id}/communications/preview", response_model=PreviewOut)
def preview(referral_id: str, body: SendIn, principal: Reader, session: DB) -> PreviewOut:
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    c = messaging.check(session, r, body.template_key)
    return PreviewOut(can_send=c.ok, problems=c.problems, body=c.body, language=c.language)


@router.post(
    "/referrals/{referral_id}/communications", response_model=CommunicationOut, status_code=201
)
def send_now(
    referral_id: str,
    body: SendIn,
    principal: Sender,
    session: DB,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Communication:
    """Staff-initiated send; the sender's action is the approval (FR-11)."""
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    c = messaging.check(session, r, body.template_key)
    if not c.ok:
        raise ValidationFailed("This message can't be sent.", details={"problems": c.problems})
    key = f"staff:{principal.user_id}:{idempotency_key or new_id('send')}"
    try:
        return messaging.send(
            session, r, body.template_key, actor=principal.actor, idempotency_key=key
        )
    except sms.TransientMessagingError as exc:
        raise ServiceUnavailable(
            "The messaging provider is unavailable. Nothing was sent; try again shortly."
        ) from exc


class InboxItem(CommunicationOut):
    patient_name: str | None
    referral_status: str | None


@router.get("/communications/inbox", response_model=list[InboxItem])
def inbox(
    principal: Reader, session: DB, include_resolved: bool = False, limit: int = Query(100, le=500)
) -> list[InboxItem]:
    """Patient replies waiting for staff (navigator queue)."""
    q = scoped(Communication, principal.organization_id).where(Communication.direction == "inbound")
    if not include_resolved:
        q = q.where(Communication.resolved_at.is_(None))
    rows = session.scalars(
        q.order_by(Communication.escalated.desc(), Communication.created_at.desc()).limit(limit)
    ).all()
    out = []
    for m in rows:
        ref = session.get(Referral, m.referral_id) if m.referral_id else None
        out.append(
            InboxItem(
                **CommunicationOut.model_validate(m).model_dump(),
                patient_name=ref.patient.display_name if ref else None,
                referral_status=ref.status if ref else None,
            )
        )
    return out


class ResolveIn(BaseModel):
    note: str = Field(min_length=2, max_length=300)


@router.post("/communications/{communication_id}/resolve", response_model=CommunicationOut)
def resolve(
    communication_id: str, body: ResolveIn, principal: Sender, session: DB
) -> Communication:
    m = get_scoped(session, Communication, communication_id, principal.organization_id)
    if m.direction != "inbound":
        raise ValidationFailed("Only patient replies can be resolved.")
    m.resolved_at, m.resolved_by = utcnow(), principal.actor
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="message.resolve",
        resource_ref=m.id,
        details={"note": "[set]"},
    )
    return m


# --- patient contact preferences ---------------------------------------------------------


class ContactIn(BaseModel):
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=254)
    preferred_language: str | None = Field(default=None, max_length=10)
    preferred_channel: Literal["sms", "email", "phone"] | None = None
    contact_verified: bool | None = None
    consent_reference: str | None = Field(default=None, max_length=120)
    opted_out: bool | None = None
    needs_interpreter: bool | None = None
    transportation_need: bool | None = None


@router.patch("/patients/{patient_id}/contact")
def update_contact(
    patient_id: str, body: ContactIn, principal: Sender, session: DB
) -> dict[str, object]:
    p = get_scoped(session, PatientReference, patient_id, principal.organization_id)
    changes = body.model_dump(exclude_none=True)
    if "phone" in changes and changes["phone"] != p.phone:
        p.contact_verified = False  # a new number must be verified again
    for k, v in changes.items():
        if k == "opted_out":
            p.opted_out_at = utcnow() if v else None
        else:
            setattr(p, k, v)
    if body.contact_verified and not p.phone and not p.email:
        raise ValidationFailed("Add a phone number or email before marking contact verified.")
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="patient.contact_update",
        resource_ref=p.id,
        details={"fields": sorted(changes)},
    )
    return {"id": p.id, "updated": sorted(changes)}


# --- templates (four-eyes review) ---------------------------------------------------------


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None
    key: str
    language: str
    version: int
    body: str
    author: str
    reviewed_by: str | None
    active: bool
    builtin: bool = False


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(principal: Reader, session: DB) -> list[TemplateOut]:
    rows = session.scalars(
        scoped(MessageTemplate, principal.organization_id).order_by(
            MessageTemplate.key, MessageTemplate.language, MessageTemplate.version.desc()
        )
    ).all()
    out = [TemplateOut.model_validate(r) for r in rows]
    have = {(r.key, r.language) for r in rows}
    for (key, lang), body in tpl_rules.BUILTIN.items():
        if (key, lang) not in have:
            out.append(
                TemplateOut(
                    id=None,
                    key=key,
                    language=lang,
                    version=0,
                    body=body,
                    author="builtin",
                    reviewed_by=None,
                    active=False,
                    builtin=True,
                )
            )
    return out


class TemplateIn(BaseModel):
    body: str = Field(min_length=10, max_length=tpl_rules.MAX_LENGTH + 100)


@router.put("/templates/{key}/{language}", response_model=TemplateOut, status_code=201)
def save_template(
    key: str, language: str, body: TemplateIn, principal: TemplateAdmin, session: DB
) -> MessageTemplate:
    if key not in tpl_rules.KEYS:
        raise ValidationFailed(f"Unknown message type {key!r}.")
    if language not in tpl_rules.LANGUAGES:
        raise ValidationFailed(f"Unsupported language {language!r}.")
    if problems := tpl_rules.problems(body.body):
        raise ValidationFailed("Template has problems.", details={"problems": problems})
    version = (
        session.scalar(
            select(func.max(MessageTemplate.version)).where(
                MessageTemplate.organization_id == principal.organization_id,
                MessageTemplate.key == key,
                MessageTemplate.language == language,
            )
        )
        or 0
    ) + 1
    t = MessageTemplate(
        organization_id=principal.organization_id,
        key=key,
        language=language,
        version=version,
        body=body.body,
        author=principal.actor,
    )
    session.add(t)
    session.flush()
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="template.save",
        resource_ref=t.id,
        details={"key": key, "language": language, "version": version},
    )
    return t


@router.post("/templates/{template_id}/review", response_model=TemplateOut)
def review_template(template_id: str, principal: TemplateAdmin, session: DB) -> MessageTemplate:
    t = get_scoped(session, MessageTemplate, template_id, principal.organization_id)
    if t.author == principal.actor:
        raise Forbidden("A different staff member must review this template.")
    if t.reviewed_by:
        raise Conflict("This version is already reviewed.")
    for old in session.scalars(
        scoped(MessageTemplate, principal.organization_id).where(
            MessageTemplate.key == t.key,
            MessageTemplate.language == t.language,
            MessageTemplate.active.is_(True),
        )
    ):
        old.active = False
    t.reviewed_by, t.reviewed_at, t.active = principal.actor, utcnow(), True
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="template.review",
        resource_ref=t.id,
    )
    return t


# --- webhooks -----------------------------------------------------------------------------

webhooks = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhooks.post("/messaging")
async def messaging_webhook(
    request: Request,
    session: DB,
    x_ab_timestamp: Annotated[str | None, Header()] = None,
    x_ab_signature: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Delivery receipts and inbound replies from the messaging provider (signed)."""
    limit(f"webhook-ip:{client_ip(request)}", limit=600, window_s=60)
    raw = await request.body()
    if not sms.verify(raw, x_ab_timestamp, x_ab_signature):
        raise Unauthorized("Invalid webhook signature.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationFailed("Body must be JSON.") from exc
    if not isinstance(payload, dict) or not payload.get("event_id"):
        raise ValidationFailed("Event needs an event_id.")
    kind = payload.get("type")
    if kind == "delivery":
        return {"result": messaging.handle_delivery(session, payload)}
    if kind == "inbound":
        return {"result": messaging.handle_inbound(session, payload)}
    raise ValidationFailed(f"Unknown event type {kind!r}.")


# --- notifications ------------------------------------------------------------------------


class NotificationOut(BaseModel):
    id: str
    referral_id: str | None
    kind: str
    message: str
    created_at: datetime
    read: bool


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    principal: AnyStaff, session: DB, unread_only: bool = False
) -> list[NotificationOut]:
    rows = session.scalars(
        scoped(Notification, principal.organization_id)
        .where(
            or_(
                Notification.user_id == principal.user_id,
                Notification.audience_role == principal.role,
            )
        )
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    out = [
        NotificationOut(
            id=n.id,
            referral_id=n.referral_id,
            kind=n.kind,
            message=n.message,
            created_at=n.created_at,
            read=principal.user_id in (n.read_by or []),
        )
        for n in rows
    ]
    return [n for n in out if not (unread_only and n.read)]


@router.post("/notifications/{notification_id}/read", status_code=204)
def mark_read(notification_id: str, principal: AnyStaff, session: DB) -> None:
    n = get_scoped(session, Notification, notification_id, principal.organization_id)
    if principal.user_id not in (n.read_by or []):
        n.read_by = [*(n.read_by or []), principal.user_id]
