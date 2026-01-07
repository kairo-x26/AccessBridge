"""Reconcile inbound integration updates with local referral state (FR-19).

Rules: duplicates are ignored; stale updates never move a referral backwards; forward moves
along the route are applied step by step with integration evidence; anything else becomes a
reconciliation task for a person. Completion additionally needs a reference to the
specialist's report, otherwise a person confirms it.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.state_machine import ROUTE, TERMINAL, TRANSITIONS, Evidence, Status
from app.integrations.fhir import SOURCE_SYSTEM, TaskUpdate
from app.models import IntegrationEvent, Referral
from app.services import audit, referrals, tasks

ACTOR = "system:fhir-reconciler"


@dataclass
class ReconcileResult:
    outcome: str  # applied | duplicate | stale | conflict | unmatched | review
    referral_id: str | None
    detail: str
    applied: list[str]


def _path(current: Status, target: Status) -> list[Status] | None:
    """Forward steps along the route from current to target, or None if not a forward move."""
    if current in ROUTE and target in ROUTE:
        i, j = ROUTE.index(current), ROUTE.index(target)
        if j <= i:
            return None
        steps = list(ROUTE[i + 1 : j + 1])
        if current in (Status.IMPORTED, Status.NEEDS_REVIEW, Status.READY):
            return None  # can't be acknowledged before we submitted it
        return steps
    if target in TRANSITIONS.get(current, frozenset()):
        return [target]
    return None


def _record(
    session: Session,
    org_id: str,
    upd: TaskUpdate,
    referral_id: str | None,
    outcome: str,
    detail: str,
) -> None:
    session.add(
        IntegrationEvent(
            organization_id=org_id,
            source=SOURCE_SYSTEM,
            external_id=upd.external_id,
            kind="fhir.task",
            referral_id=referral_id,
            outcome=outcome,
            detail=detail[:500],
        )
    )
    session.flush()


def reconcile_task(session: Session, organization_id: str, upd: TaskUpdate) -> ReconcileResult:
    seen = session.scalar(
        select(IntegrationEvent).where(
            IntegrationEvent.organization_id == organization_id,
            IntegrationEvent.source == SOURCE_SYSTEM,
            IntegrationEvent.external_id == upd.external_id,
        )
    )
    if seen:
        return ReconcileResult("duplicate", seen.referral_id, "Already processed", [])

    ref = session.scalar(
        select(Referral).where(
            Referral.organization_id == organization_id,
            Referral.source_id == upd.source_request_id,
            Referral.source_system == SOURCE_SYSTEM,
        )
    )
    if ref is None:
        _record(
            session,
            organization_id,
            upd,
            None,
            "unmatched",
            f"No referral for ServiceRequest/{upd.source_request_id}",
        )
        return ReconcileResult("unmatched", None, "No matching referral", [])

    current = Status(ref.status)
    target = upd.proposed_status
    evidence_ref = f"fhir:{upd.external_id}"

    def conflict(detail: str, outcome: str = "conflict") -> ReconcileResult:
        tasks.ensure_task(
            session,
            organization_id=organization_id,
            referral_id=ref.id,
            kind="reconciliation",
            title="Specialist system update needs review",
            detail=detail,
            priority="high",
            owner_id=ref.owner_id,
            created_by=ACTOR,
            dedupe_key=f"reconcile:{ref.id}:{upd.external_id}",
            data={"fhir_status": upd.fhir_status, "proposed": target.value if target else None},
        )
        _record(session, organization_id, upd, ref.id, outcome, detail)
        audit.record(
            session,
            organization_id=organization_id,
            actor=ACTOR,
            operation="integration.reconcile",
            resource_ref=ref.id,
            outcome=outcome,
            details={"external_id": upd.external_id},
        )
        return ReconcileResult(outcome, ref.id, detail, [])

    if target is None:
        return conflict(f"Unrecognized Task status '{upd.fhir_status}'.")
    if target == current:
        if upd.appointment_at and ref.appointment_at != upd.appointment_at:
            ref.appointment_at = upd.appointment_at
        _record(session, organization_id, upd, ref.id, "applied", "No status change")
        return ReconcileResult("applied", ref.id, "No status change", [])
    if current in TERMINAL:
        return conflict(
            f"Specialist system reports '{upd.fhir_status}' but the referral is "
            f"already {current.value}."
        )
    if current == Status.EXCEPTION:
        return conflict(
            f"Specialist system reports '{upd.fhir_status}' while the referral is "
            "an open exception."
        )
    if target == Status.EXCEPTION:
        referrals.transition(
            session,
            ref,
            Status.EXCEPTION,
            actor=ACTOR,
            reason=f"Specialist system reported failure: {upd.note or 'no detail'}",
        )
        _record(session, organization_id, upd, ref.id, "applied", "Moved to exception")
        return ReconcileResult("applied", ref.id, "Moved to exception", ["exception"])
    if target in (Status.DECLINED, Status.CANCELLED):
        if target not in TRANSITIONS[current]:
            return conflict(f"Can't apply '{upd.fhir_status}' from {current.value}.")
        referrals.transition(
            session,
            ref,
            target,
            actor=ACTOR,
            evidence_type=Evidence.FHIR_TASK_UPDATE.value,
            evidence_reference=evidence_ref,
            reason=upd.note or f"Specialist system: {upd.fhir_status}",
        )
        _record(session, organization_id, upd, ref.id, "applied", f"Moved to {target.value}")
        return ReconcileResult("applied", ref.id, f"Moved to {target.value}", [target.value])

    if current in ROUTE and ROUTE.index(target) < ROUTE.index(current):
        _record(session, organization_id, upd, ref.id, "stale", "Older than local state")
        return ReconcileResult("stale", ref.id, "Older than local state; ignored", [])

    steps = _path(current, target)
    if not steps:
        return conflict(
            f"Specialist system reports '{upd.fhir_status}' but the referral is "
            f"{current.value}; it has not been submitted from here."
        )
    if target == Status.COMPLETED and not upd.completion_reference:
        # Apply what is proven, leave completion to a person.
        steps = steps[:-1]
        for step in steps:
            referrals.transition(
                session,
                ref,
                step,
                actor=ACTOR,
                evidence_type=Evidence.FHIR_TASK_UPDATE.value,
                evidence_reference=evidence_ref,
            )
        result = conflict(
            "Specialist system marked this referral complete without a consult "
            "note. Confirm completion with evidence.",
            outcome="review",
        )
        result.applied = [s.value for s in steps]
        return result
    for step in steps:
        referrals.transition(
            session,
            ref,
            step,
            actor=ACTOR,
            evidence_type=Evidence.FHIR_TASK_UPDATE.value,
            evidence_reference=(
                f"{evidence_ref} report={upd.completion_reference}"
                if step == Status.COMPLETED
                else evidence_ref
            ),
        )
    if upd.appointment_at:
        ref.appointment_at = upd.appointment_at
    detail = f"Applied {', '.join(s.value for s in steps)}"
    _record(session, organization_id, upd, ref.id, "applied", detail)
    return ReconcileResult("applied", ref.id, detail, [s.value for s in steps])


def reconcile_task_safely(
    session: Session, organization_id: str, upd: TaskUpdate
) -> ReconcileResult:
    """Concurrent deliveries of the same update race on the unique key; the loser is a dup."""
    try:
        with session.begin_nested():
            return reconcile_task(session, organization_id, upd)
    except IntegrityError:
        return ReconcileResult("duplicate", None, "Already processed", [])
