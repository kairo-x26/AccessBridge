"""Referral package review and approval (FR-07, workflow A steps 5–6)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import Conflict, ValidationFailed
from app.domain.state_machine import Evidence, Status
from app.models import (
    ExtractedField,
    Referral,
    ReferralDocument,
    ReferralPackage,
    User,
    ValidationIssue,
)
from app.services import audit, referrals, tasks, validation


def contents(session: Session, referral: Referral) -> dict[str, Any]:
    fields = session.scalars(
        select(ExtractedField).where(
            ExtractedField.referral_id == referral.id, ExtractedField.status != "rejected"
        )
    )
    chosen: dict[str, ExtractedField] = {}
    for f in fields:
        cur = chosen.get(f.name)
        rank = (f.status in ("accepted", "corrected"), f.confidence)
        if cur is None or rank > (cur.status in ("accepted", "corrected"), cur.confidence):
            chosen[f.name] = f
    docs = session.scalars(
        select(ReferralDocument)
        .where(ReferralDocument.referral_id == referral.id)
        .order_by(ReferralDocument.created_at)
    )
    _, checklist_version = validation.checklist_for(
        session, referral.organization_id, referral.specialty
    )
    return {
        "referral_id": referral.id,
        "specialty": referral.specialty,
        "priority_from_source": referral.priority_from_source,
        "provider_id": referral.provider_id,
        "patient_ref_id": referral.patient_ref_id,
        "checklist_version": checklist_version,
        "fields": {
            name: {
                "value": f.effective_value,
                "status": f.status,
                "field_id": f.id,
                "document_id": f.document_id,
                "span": [f.span_start, f.span_end],
            }
            for name, f in sorted(chosen.items())
        },
        "documents": [
            {"id": d.id, "checksum": d.checksum, "doc_type": d.doc_type, "filename": d.filename}
            for d in docs
        ],
    }


def readiness(session: Session, referral: Referral) -> list[str]:
    """Reasons the package can't be approved yet; empty when ready."""
    reasons = []
    if Status(referral.status) != Status.NEEDS_REVIEW:
        reasons.append(
            "Move this referral back to review before approving the package."
            if referral.status == "exception"
            else "The package was already approved for this referral."
        )
    blocking = session.scalars(
        select(ValidationIssue).where(
            ValidationIssue.referral_id == referral.id,
            ValidationIssue.status == "open",
            ValidationIssue.severity == "blocking",
        )
    ).all()
    reasons += [i.message for i in blocking]
    unreviewed = session.scalars(
        select(ExtractedField).where(
            ExtractedField.referral_id == referral.id,
            ExtractedField.critical.is_(True),
            ExtractedField.status == "candidate",
        )
    ).all()
    for name in sorted({f.name for f in unreviewed}):
        reasons.append(f"Confirm the {name.replace('_', ' ')} extracted from the documents.")
    return reasons


def approve(
    session: Session, referral: Referral, reviewer: User, *, note: str | None, expected_version: int
) -> ReferralPackage:
    if expected_version != referral.version:
        raise Conflict(
            "This referral changed since you loaded it. Refresh and review again.",
            details={"current_version": referral.version},
        )
    validation.sync_issues(session, referral, actor=f"user:{reviewer.id}")
    problems = readiness(session, referral)
    if problems:
        raise ValidationFailed("The package isn't ready to approve.", details={"reasons": problems})
    body = contents(session, referral)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    version = (
        session.scalar(
            select(func.max(ReferralPackage.version)).where(
                ReferralPackage.referral_id == referral.id
            )
        )
        or 0
    ) + 1
    pkg = ReferralPackage(
        organization_id=referral.organization_id,
        referral_id=referral.id,
        version=version,
        contents=body,
        content_hash=digest,
        approved_by=reviewer.id,
        note=note,
    )
    session.add(pkg)
    session.flush()
    referral.package_approved_by = reviewer.id
    referral.package_approved_at = utcnow()
    referrals.transition(
        session,
        referral,
        Status.READY,
        actor=f"user:{reviewer.id}",
        evidence_type=Evidence.PACKAGE_APPROVAL.value,
        evidence_reference=f"package:{pkg.id}:sha256:{digest[:16]}",
    )
    audit.record(
        session,
        organization_id=referral.organization_id,
        actor=f"user:{reviewer.id}",
        operation="package.approve",
        resource_ref=pkg.id,
        details={"referral_id": referral.id, "version": version},
    )
    tasks.resolve_by_key(
        session,
        referral.organization_id,
        f"agent:{referral.id}:review_package",
        actor=f"user:{reviewer.id}",
        resolution="Package approved",
    )
    return pkg


def review_field(
    session: Session,
    f: ExtractedField,
    reviewer: User,
    *,
    action: str,
    corrected_value: str | None = None,
) -> ExtractedField:
    if action == "correct":
        if not corrected_value or not corrected_value.strip():
            raise ValidationFailed("Enter the corrected value.")
        f.corrected_value = corrected_value.strip()
        f.status = "corrected"
    elif action == "accept":
        f.status = "accepted"
        f.corrected_value = None
    elif action == "reject":
        f.status = "rejected"
    else:
        raise ValidationFailed("Action must be accept, correct or reject.")
    f.reviewed_by = reviewer.id
    f.reviewed_at = utcnow()
    audit.record(
        session,
        organization_id=f.organization_id,
        actor=f"user:{reviewer.id}",
        operation=f"field.{action}",
        resource_ref=f.id,
        details={"name": f.name, "referral_id": f.referral_id},
    )
    return f
