"""Patient communication (FR-11, FR-12): sending checks, delivery tracking, replies.

A message goes out only if every check passes: the patient hasn't opted out, consent is on
record, the contact is verified, a reviewed template exists in the patient's language, and
the same message wasn't sent recently. A failed check is recorded as a suppressed message
with a staff task — never silently dropped.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.domain import templates as tpl_rules
from app.integrations import sms
from app.models import (
    Communication,
    IntegrationEvent,
    MessageTemplate,
    Organization,
    PatientReference,
    Referral,
)
from app.services import audit, response_classifier, tasks

RESEND_WINDOW = timedelta(days=3)


def address_hash(address: str) -> str:
    digits = "".join(c for c in address if c.isdigit())[-10:] or address.strip().lower()
    key = hashlib.sha256(("addr:" + get_settings().jwt_secret).encode()).digest()
    return hmac.new(key, digits.encode(), hashlib.sha256).hexdigest()


def active_template(
    session: Session, organization_id: str, key: str, language: str
) -> MessageTemplate | None:
    return session.scalar(
        select(MessageTemplate).where(
            MessageTemplate.organization_id == organization_id,
            MessageTemplate.key == key,
            MessageTemplate.language == language,
            MessageTemplate.active.is_(True),
        )
    )


@dataclass
class SendCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    template: MessageTemplate | None = None
    body: str | None = None
    language: str | None = None


def check(session: Session, referral: Referral, template_key: str) -> SendCheck:
    p: PatientReference = referral.patient
    problems = []
    if template_key not in tpl_rules.KEYS:
        problems.append(f"Unknown message type {template_key!r}.")
    if p.opted_out_at:
        problems.append("Patient opted out of text messages.")
    if not p.consent_reference:
        problems.append("No consent to text messages on record.")
    if not p.contact_verified:
        problems.append("Patient contact details aren't verified.")
    if p.preferred_channel != "sms":
        problems.append(f"Patient prefers {p.preferred_channel}; text messages aren't allowed.")
    if not p.phone:
        problems.append("No phone number on file.")
    template = active_template(
        session, referral.organization_id, template_key, p.preferred_language
    )
    if template is None:
        lang = tpl_rules.LANGUAGES.get(p.preferred_language, p.preferred_language)
        problems.append(f"No reviewed '{template_key}' message in {lang}.")
    recent = session.scalar(
        select(Communication.id).where(
            Communication.referral_id == referral.id,
            Communication.direction == "outbound",
            Communication.template_key == template_key,
            Communication.status.in_(("sent", "delivered")),
            Communication.sent_at > utcnow() - RESEND_WINDOW,
        )
    )
    if recent:
        problems.append("This message was already sent in the last 3 days.")
    body = None
    if template is not None:
        org = session.get(Organization, referral.organization_id)
        prov = referral.provider
        body = tpl_rules.render(
            template.body,
            {
                "first_name": p.given_name.split()[0],
                "clinic_name": org.name if org else "your clinic",
                "specialist_office": prov.name if prov else "the specialist office",
                "specialist_phone": (
                    prov.phone if prov and prov.phone else "the number on your referral"
                ),
            },
        )
    return SendCheck(not problems, problems, template, body, p.preferred_language)


def send(
    session: Session,
    referral: Referral,
    template_key: str,
    *,
    actor: str,
    idempotency_key: str,
    action_id: str | None = None,
) -> Communication:
    existing = session.scalar(
        select(Communication).where(Communication.idempotency_key == idempotency_key)
    )
    if existing:
        return existing
    c = check(session, referral, template_key)
    p = referral.patient
    msg = Communication(
        organization_id=referral.organization_id,
        referral_id=referral.id,
        patient_ref_id=p.id,
        direction="outbound",
        channel="sms",
        template_key=template_key,
        template_id=c.template.id if c.template else None,
        language=c.language,
        body=c.body,
        address=p.phone,
        address_hash=address_hash(p.phone) if p.phone else None,
        consent_reference=p.consent_reference,
        created_by=actor,
        action_id=action_id,
        idempotency_key=idempotency_key,
        status="queued",
    )
    session.add(msg)
    session.flush()
    if not c.ok:
        msg.status = "suppressed"
        msg.failure_reason = " ".join(c.problems)[:300]
        tasks.ensure_task(
            session,
            organization_id=referral.organization_id,
            referral_id=referral.id,
            kind="patient_assistance",
            title="Reach the patient another way",
            detail=f"An automated message wasn't sent: {msg.failure_reason}",
            created_by=actor,
            owner_id=referral.owner_id,
            dedupe_key=f"suppressed:{referral.id}:{template_key}",
        )
    else:
        assert p.phone and c.body
        try:
            mid, _ = sms.gateway.send(to=p.phone, body=c.body, idempotency_key=idempotency_key)
        except sms.PermanentMessagingError as exc:
            msg.status, msg.failure_reason = "failed", str(exc)
            p.contact_verified = False
            tasks.ensure_task(
                session,
                organization_id=referral.organization_id,
                referral_id=referral.id,
                kind="patient_assistance",
                title="Patient phone number doesn't work",
                detail=str(exc),
                created_by=actor,
                owner_id=referral.owner_id,
                dedupe_key=f"invalid-contact:{p.id}",
            )
        else:
            msg.status, msg.provider_message_id, msg.sent_at = "sent", mid, utcnow()
    audit.record(
        session,
        organization_id=referral.organization_id,
        actor=actor,
        operation="message.send",
        resource_ref=msg.id,
        outcome=msg.status,
        details={
            "referral_id": referral.id,
            "template": template_key,
            "consent_reference": p.consent_reference,
            "action_id": action_id,
        },
    )
    return msg


# --- webhooks -------------------------------------------------------------------------


def _seen(
    session: Session,
    organization_id: str,
    event_id: str,
    kind: str,
    referral_id: str | None,
    outcome: str,
) -> bool:
    if session.scalar(
        select(IntegrationEvent.id).where(
            IntegrationEvent.organization_id == organization_id,
            IntegrationEvent.source == "messaging",
            IntegrationEvent.external_id == event_id,
        )
    ):
        return True
    session.add(
        IntegrationEvent(
            organization_id=organization_id,
            source="messaging",
            external_id=event_id,
            kind=kind,
            referral_id=referral_id,
            outcome=outcome,
        )
    )
    session.flush()
    return False


def handle_delivery(session: Session, payload: dict[str, Any]) -> str:
    msg = session.scalar(
        select(Communication).where(
            Communication.provider_message_id == str(payload.get("message_id", ""))
        )
    )
    if msg is None:
        return "unmatched"
    if _seen(
        session,
        msg.organization_id,
        str(payload["event_id"]),
        "delivery",
        msg.referral_id,
        "applied",
    ):
        return "duplicate"
    status = payload.get("status")
    if status == "delivered" and msg.status == "sent":
        msg.status, msg.delivered_at = "delivered", utcnow()
    elif status == "failed" and msg.status in ("sent", "delivered"):
        msg.status = "failed"
        msg.failure_reason = str(payload.get("error") or "Carrier reported failure")[:300]
        if msg.referral_id:
            tasks.ensure_task(
                session,
                organization_id=msg.organization_id,
                referral_id=msg.referral_id,
                kind="patient_assistance",
                title="Text message wasn't delivered",
                detail=msg.failure_reason,
                created_by="system:messaging",
                dedupe_key=f"undelivered:{msg.id}",
            )
    audit.record(
        session,
        organization_id=msg.organization_id,
        actor="system:messaging",
        operation="message.delivery",
        resource_ref=msg.id,
        outcome=msg.status,
    )
    return "applied"


def handle_inbound(session: Session, payload: dict[str, Any]) -> str:
    org = session.scalar(
        select(Organization).where(Organization.slug == str(payload.get("account", "")))
    )
    if org is None:
        return "unmatched"
    if _seen(session, org.id, str(payload["event_id"]), "inbound", None, "applied"):
        return "duplicate"
    sender = str(payload.get("from", ""))
    text = str(payload.get("body", ""))[:2000]
    h = address_hash(sender)
    recent = session.scalars(
        select(Communication)
        .where(
            Communication.organization_id == org.id,
            Communication.direction == "outbound",
            Communication.address_hash == h,
            Communication.sent_at.is_not(None),
            Communication.sent_at > utcnow() - timedelta(days=30),
        )
        .order_by(Communication.sent_at.desc())
    ).all()
    patients = {m.patient_ref_id for m in recent}
    last = recent[0] if recent else None
    inbound = Communication(
        organization_id=org.id,
        direction="inbound",
        channel="sms",
        body=text,
        address=sender,
        address_hash=h,
        status="received",
        created_by="system:messaging",
        referral_id=last.referral_id if last and len(patients) == 1 else None,
        patient_ref_id=last.patient_ref_id if last and len(patients) == 1 else None,
        in_reply_to=last.id if last and len(patients) == 1 else None,
    )
    session.add(inbound)
    session.flush()
    result = response_classifier.classify(session, org.id, text)
    inbound.classification, inbound.classified_by = result.category, result.method
    inbound.escalated = result.escalate

    if len(patients) > 1:
        # Shared phone: we can't tell who replied. Never act on it automatically.
        inbound.escalated = True
        tasks.ensure_task(
            session,
            organization_id=org.id,
            kind="patient_assistance",
            priority="high",
            title="Reply from a shared phone number",
            detail="More than one patient uses this number. Identify who replied before acting.",
            created_by="system:messaging",
            dedupe_key=f"shared-number:{inbound.id}",
        )
        return "identity_uncertain"
    if inbound.referral_id is None:
        tasks.ensure_task(
            session,
            organization_id=org.id,
            kind="patient_assistance",
            title="Text from an unknown number",
            created_by="system:messaging",
            detail="No recent message was sent to this number.",
            dedupe_key=f"unknown-sender:{inbound.id}",
        )
        return "unmatched_sender"
    _route(session, inbound, result)
    audit.record(
        session,
        organization_id=org.id,
        actor="system:messaging",
        operation="message.inbound",
        resource_ref=inbound.id,
        details={
            "classification": result.category,
            "escalated": inbound.escalated,
            "referral_id": inbound.referral_id,
        },
    )
    return "applied"


def _route(
    session: Session, inbound: Communication, result: response_classifier.Classification
) -> None:
    ref = session.get(Referral, inbound.referral_id)
    assert ref is not None
    org_id = ref.organization_id
    actor = "system:messaging"
    if result.escalate:
        tasks.ensure_task(
            session,
            organization_id=org_id,
            referral_id=ref.id,
            kind="patient_assistance",
            priority="urgent",
            title="Patient reply needs clinical staff",
            detail=result.reason,
            created_by=actor,
            dedupe_key=f"escalate:{inbound.id}",
            data={"communication_id": inbound.id},
        )
        return
    if result.category == "opt_out":
        ref.patient.opted_out_at = utcnow()
        inbound.resolved_at, inbound.resolved_by = utcnow(), actor
        audit.record(
            session,
            organization_id=org_id,
            actor=actor,
            operation="patient.opt_out",
            resource_ref=ref.patient_ref_id,
        )
        return
    if result.category == "needs_assistance":
        tasks.ensure_task(
            session,
            organization_id=org_id,
            referral_id=ref.id,
            kind="patient_assistance",
            priority="high",
            title="Patient asked for help",
            created_by=actor,
            detail="Contact the patient about scheduling, transport, cost or language support.",
            dedupe_key=f"assist:{ref.id}",
            data={"communication_id": inbound.id},
        )
    elif result.category == "declined":
        tasks.ensure_task(
            session,
            organization_id=org_id,
            referral_id=ref.id,
            kind="follow_up",
            title="Patient may not want this referral",
            created_by=actor,
            detail="Confirm with the patient before closing it as declined.",
            dedupe_key=f"declined:{ref.id}",
            data={"communication_id": inbound.id},
        )
    elif result.category == "confirmed":
        # Evidence for a status change only after staff approval; the follow-up agent
        # proposes it.
        from app.agents import orchestrator

        orchestrator.start_run(
            session, ref, workflow="follow_up", trigger=actor, idempotency_key=f"reply:{inbound.id}"
        )
    else:
        tasks.ensure_task(
            session,
            organization_id=org_id,
            referral_id=ref.id,
            kind="patient_assistance",
            title="Read the patient's reply",
            created_by=actor,
            dedupe_key=f"unknown-reply:{inbound.id}",
            data={"communication_id": inbound.id},
        )
