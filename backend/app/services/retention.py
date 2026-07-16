"""Retention (spec §8 lifecycle step 5): purge working data from long-closed referrals.

What goes: stored documents and their extracted text, extracted values, message bodies and
addresses, and patient contact details once the patient has no other open referral.
What stays: the referral skeleton, its status history and the audit trail, which carry no
document content, so outcome reporting and accountability survive the purge.
Legal holds override retention.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.domain.state_machine import TERMINAL
from app.models import (
    Communication,
    ExtractedField,
    Organization,
    PatientReference,
    Referral,
    ReferralDocument,
)
from app.services import audit, storage

TERMINAL_VALUES = tuple(s.value for s in TERMINAL)


def purge_referral(session: Session, r: Referral, *, actor: str) -> dict[str, int]:
    docs = list(
        session.scalars(select(ReferralDocument).where(ReferralDocument.referral_id == r.id))
    )
    shared = {
        d.checksum
        for d in docs
        if session.scalar(
            select(ReferralDocument.id).where(
                ReferralDocument.checksum == d.checksum,
                ReferralDocument.referral_id != r.id,
                ReferralDocument.organization_id == r.organization_id,
            )
        )
    }
    files = 0
    for d in docs:
        if d.checksum not in shared:
            files += storage.delete(d.storage_uri, r.organization_id)
        d.text_content = None
        d.extraction_status = "purged"
    fields = 0
    for f in session.scalars(select(ExtractedField).where(ExtractedField.referral_id == r.id)):
        session.delete(f)
        fields += 1
    messages = 0
    for m in session.scalars(select(Communication).where(Communication.referral_id == r.id)):
        m.body, m.address = None, None
        messages += 1
    other_open = session.scalar(
        select(Referral.id).where(
            Referral.patient_ref_id == r.patient_ref_id,
            Referral.id != r.id,
            Referral.status.not_in(TERMINAL_VALUES),
        )
    )
    if not other_open:
        p = session.get(PatientReference, r.patient_ref_id)
        if p is not None:
            p.phone = p.email = p.birth_date = None
            p.contact_verified = False
    r.reason_from_source = None
    r.purged_at = utcnow()
    counts = {"files": files, "fields": fields, "messages": messages}
    audit.record(
        session,
        organization_id=r.organization_id,
        actor=actor,
        operation="retention.purge",
        resource_ref=r.id,
        details=counts,
    )
    return counts


def sweep(session: Session, *, now: datetime | None = None) -> int:
    now = now or utcnow()
    purged = 0
    for org in session.scalars(select(Organization)):
        cutoff = now - timedelta(days=org.retention_days)
        for r in session.scalars(
            select(Referral).where(
                Referral.organization_id == org.id,
                Referral.status.in_(TERMINAL_VALUES),
                Referral.legal_hold.is_(False),
                Referral.purged_at.is_(None),
                Referral.status_changed_at < cutoff,
            )
        ):
            purge_referral(session, r, actor="system:retention")
            purged += 1
    return purged
