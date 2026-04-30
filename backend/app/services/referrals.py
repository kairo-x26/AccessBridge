"""Referral records: intake, evidence-backed state changes and queries (FR-03, FR-04)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import Conflict, InvalidTransition
from app.domain.state_machine import ROUTE, TERMINAL, Status, check_transition
from app.models import (
    ExternalProvider,
    PatientReference,
    Referral,
    ReferralDocument,
    ReferralStatusEvent,
    Task,
)
from app.services import audit, storage, tasks

SUPPORTED_SPECIALTIES = (
    "cardiology",
    "dermatology",
    "endocrinology",
    "gastroenterology",
    "neurology",
    "orthopedics",
    "ophthalmology",
    "behavioral_health",
)


@dataclass
class PatientIn:
    ehr_patient_id: str
    given_name: str
    family_name: str
    birth_date: str | None = None
    phone: str | None = None
    email: str | None = None
    preferred_language: str = "en"
    preferred_channel: str = "sms"
    consent_reference: str | None = None


@dataclass
class DocumentIn:
    filename: str
    content_type: str
    data: bytes


@dataclass
class IntakeRecord:
    source_system: str
    source_id: str
    patient: PatientIn
    specialty: str
    priority_from_source: str = "routine"
    reason_from_source: str | None = None
    referring_clinician: str | None = None
    provider_name: str | None = None
    provider_reference: str | None = None
    documents: list[DocumentIn] = field(default_factory=list)

    def content_hash(self) -> str:
        body = asdict(self)
        body["documents"] = sorted(storage.checksum(d.data) for d in self.documents)
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class IngestResult:
    referral: Referral
    duplicate: bool
    identity_conflict: bool = False
    source_changed: bool = False


TransitionHook = Callable[[Session, Referral, ReferralStatusEvent], None]
_hooks: list[TransitionHook] = []


def on_transition(hook: TransitionHook) -> TransitionHook:
    """Register a callback run after every committed-to-session status change."""
    _hooks.append(hook)
    return hook


# --- State changes ----------------------------------------------------------------


def transition(
    session: Session,
    referral: Referral,
    target: Status | str,
    *,
    actor: str,
    evidence_type: str | None = None,
    evidence_reference: str | None = None,
    reason: str | None = None,
    correction: bool = False,
    expected_version: int | None = None,
) -> ReferralStatusEvent:
    target = Status(target)
    current = Status(referral.status)
    if expected_version is not None and expected_version != referral.version:
        raise Conflict(
            "This referral changed since you loaded it. Refresh and try again.",
            details={"current_version": referral.version, "current_status": current.value},
        )
    err = check_transition(
        current,
        target,
        evidence_type=evidence_type,
        evidence_reference=evidence_reference,
        reason=reason,
        correction=correction,
    )
    if err:
        audit.record_detached(
            organization_id=referral.organization_id,
            actor=actor,
            operation="referral.transition",
            resource_ref=referral.id,
            outcome="rejected",
            details={"from": current.value, "to": target.value, "code": err.code},
        )
        raise InvalidTransition(
            err.message, details={"code": err.code, "from": current.value, "to": target.value}
        )
    event = ReferralStatusEvent(
        organization_id=referral.organization_id,
        referral_id=referral.id,
        old_status=current.value,
        new_status=target.value,
        evidence_type=evidence_type,
        evidence_reference=evidence_reference,
        reason=reason,
        actor=actor,
        correction=correction,
    )
    session.add(event)
    referral.status = target.value
    if target in ROUTE:
        referral.progress_status = target.value
    referral.status_changed_at = utcnow()
    referral.version += 1
    referral.exception_reason = reason if target == Status.EXCEPTION else None
    session.flush()
    audit.record(
        session,
        organization_id=referral.organization_id,
        actor=actor,
        operation="referral.transition",
        resource_ref=referral.id,
        details={
            "from": current.value,
            "to": target.value,
            "evidence_type": evidence_type,
            "event_id": event.id,
            "correction": correction,
        },
    )

    if target == Status.EXCEPTION:
        tasks.ensure_task(
            session,
            organization_id=referral.organization_id,
            referral_id=referral.id,
            kind="exception",
            title="Resolve referral exception",
            detail=reason,
            priority="high",
            owner_id=referral.owner_id,
            created_by=actor,
            dedupe_key=f"exception:{referral.id}",
        )
    if current == Status.EXCEPTION:
        tasks.resolve_by_key(
            session,
            referral.organization_id,
            f"exception:{referral.id}",
            actor=actor,
            resolution=f"Referral moved to {target.value}",
        )
    if target in TERMINAL:
        for t in session.scalars(
            select(Task).where(Task.referral_id == referral.id, Task.status.in_(tasks.OPEN_STATES))
        ):
            tasks.resolve(
                session,
                t,
                actor=actor,
                status="cancelled",
                resolution=f"Referral closed as {target.value}",
            )
    for hook in _hooks:
        hook(session, referral, event)
    return event


# --- Intake -----------------------------------------------------------------------


def _match_provider(
    session: Session, organization_id: str, record: IntakeRecord
) -> ExternalProvider | None:
    q = select(ExternalProvider).where(ExternalProvider.organization_id == organization_id)
    if record.provider_reference:
        # A stated identifier that matches nothing is not overridden by a look-alike name;
        # the coordinator picks the destination instead.
        return session.scalar(
            q.where(ExternalProvider.network_reference == record.provider_reference)
        )
    if record.provider_name:
        return session.scalar(q.where(ExternalProvider.name == record.provider_name))
    return None


def _identity_conflicts(existing: PatientReference, incoming: PatientIn) -> list[str]:
    diffs = []
    if existing.family_name.strip().lower() != incoming.family_name.strip().lower():
        diffs.append("family_name")
    if existing.given_name.strip().lower() != incoming.given_name.strip().lower():
        diffs.append("given_name")
    if existing.birth_date and incoming.birth_date and existing.birth_date != incoming.birth_date:
        diffs.append("birth_date")
    return diffs


def add_document(
    session: Session, referral: Referral, doc: DocumentIn, *, actor: str, source_system: str
) -> tuple[ReferralDocument, bool]:
    uri, digest = storage.put(referral.organization_id, doc.data)
    existing = session.scalar(
        select(ReferralDocument).where(
            ReferralDocument.referral_id == referral.id, ReferralDocument.checksum == digest
        )
    )
    if existing:
        return existing, False
    row = ReferralDocument(
        organization_id=referral.organization_id,
        referral_id=referral.id,
        filename=doc.filename[:255],
        content_type=doc.content_type,
        storage_uri=uri,
        checksum=digest,
        size_bytes=len(doc.data),
        source_system=source_system,
        uploaded_by=actor,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        organization_id=referral.organization_id,
        actor=actor,
        operation="document.add",
        resource_ref=row.id,
        details={"referral_id": referral.id, "size": len(doc.data)},
    )
    return row, True


def ingest(
    session: Session, organization_id: str, record: IntakeRecord, *, actor: str
) -> IngestResult:
    existing = session.scalar(
        select(Referral).where(
            Referral.organization_id == organization_id,
            Referral.source_system == record.source_system,
            Referral.source_id == record.source_id,
        )
    )
    digest = record.content_hash()
    if existing:
        changed = existing.content_hash != digest
        if changed:
            # Never silently overwrite reviewed data; a person decides what the change means.
            for doc in record.documents:
                add_document(
                    session, existing, doc, actor=actor, source_system=record.source_system
                )
            tasks.ensure_task(
                session,
                organization_id=organization_id,
                referral_id=existing.id,
                kind="reconciliation",
                title="Source sent an updated referral",
                detail="The referring system re-sent this referral with different content. "
                "Compare it with the current record.",
                created_by=actor,
                dedupe_key=f"source-changed:{existing.id}:{digest[:12]}",
            )
        audit.record(
            session,
            organization_id=organization_id,
            actor=actor,
            operation="referral.import",
            resource_ref=existing.id,
            outcome="duplicate",
            details={"source_changed": changed},
        )
        return IngestResult(existing, duplicate=True, source_changed=changed)

    p = record.patient
    patient = session.scalar(
        select(PatientReference).where(
            PatientReference.organization_id == organization_id,
            PatientReference.ehr_patient_id == p.ehr_patient_id,
        )
    )
    conflicts: list[str] = []
    if patient is None:
        patient = PatientReference(
            organization_id=organization_id,
            ehr_patient_id=p.ehr_patient_id,
            given_name=p.given_name,
            family_name=p.family_name,
            birth_date=p.birth_date,
            phone=p.phone,
            email=p.email,
            preferred_language=p.preferred_language,
            preferred_channel=p.preferred_channel,
            consent_reference=p.consent_reference,
        )
        session.add(patient)
        session.flush()
    else:
        conflicts = _identity_conflicts(patient, p)

    provider = _match_provider(session, organization_id, record)
    referral = Referral(
        organization_id=organization_id,
        patient_ref_id=patient.id,
        source_system=record.source_system,
        source_id=record.source_id,
        specialty=record.specialty,
        priority_from_source=record.priority_from_source,
        reason_from_source=record.reason_from_source,
        referring_clinician=record.referring_clinician,
        provider_id=provider.id if provider else None,
        content_hash=digest,
    )
    session.add(referral)
    session.flush()
    session.add(
        ReferralStatusEvent(
            organization_id=organization_id,
            referral_id=referral.id,
            old_status=None,
            new_status=Status.IMPORTED.value,
            actor=actor,
            evidence_type="source_record",
            evidence_reference=f"{record.source_system}:{record.source_id}",
        )
    )
    audit.record(
        session,
        organization_id=organization_id,
        actor=actor,
        operation="referral.import",
        resource_ref=referral.id,
        details={"source_system": record.source_system, "documents": len(record.documents)},
    )
    for doc in record.documents:
        add_document(session, referral, doc, actor=actor, source_system=record.source_system)

    transition(session, referral, Status.NEEDS_REVIEW, actor=actor)
    if conflicts:
        transition(
            session,
            referral,
            Status.EXCEPTION,
            actor=actor,
            reason="Patient identity doesn't match the existing record "
            f"({', '.join(conflicts)}). Confirm identity before continuing.",
        )
    return IngestResult(referral, duplicate=False, identity_conflict=bool(conflicts))


def age_days(referral: Referral, now: datetime | None = None) -> int:
    created = referral.created_at
    if created.tzinfo is None:
        from datetime import UTC

        created = created.replace(tzinfo=UTC)
    return max(0, ((now or utcnow()) - created).days)
