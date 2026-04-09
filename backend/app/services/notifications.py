"""In-app notifications for the clinical team (Workflow C step 5)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Notification, Referral, ReferralStatusEvent
from app.services import referrals


def care_completed(session: Session, referral: Referral, *, evidence: str) -> Notification:
    specialty = referral.specialty.replace("_", " ")
    n = Notification(
        organization_id=referral.organization_id,
        audience_role="clinician",
        referral_id=referral.id,
        kind="care_completed",
        message=f"{referral.patient.display_name} completed the {specialty} referral ({evidence}).",
    )
    session.add(n)
    session.flush()
    return n


@referrals.on_transition
def _notify_on_completion(session: Session, referral: Referral, event: ReferralStatusEvent) -> None:
    """Every path to completion (agent, staff, specialist system) notifies the clinicians."""
    if event.new_status == "completed":
        care_completed(session, referral, evidence=event.evidence_type or "evidence on file")
