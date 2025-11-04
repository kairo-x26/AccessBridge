"""Referral state machine (spec §6 "Referral state model").

Pure, dependency-free rules. The service layer calls :func:`check_transition` before any
status change; nothing else (including AI output) can move a referral.

Key rules:
* only edges drawn in the spec are legal;
* every move into a progress state needs evidence of an accepted kind;
* ``COMPLETED`` needs evidence of *completed care* — a delivered message or a patient
  saying "yes" is not enough (spec §7, physician story);
* ``EXCEPTION`` is operational and needs a reason;
* terminal states can only be left through an authorized correction, which goes to
  ``EXCEPTION`` with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    IMPORTED = "imported"
    NEEDS_REVIEW = "needs_review"
    READY = "ready"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    EXCEPTION = "exception"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class Evidence(StrEnum):
    TRANSMISSION_RECEIPT = "transmission_receipt"
    MANUAL_SUBMISSION_NOTE = "manual_submission_note"
    SPECIALIST_ACKNOWLEDGMENT = "specialist_acknowledgment"
    PHONE_CONFIRMATION = "phone_confirmation"
    APPOINTMENT_RECORD = "appointment_record"
    PATIENT_CONFIRMATION = "patient_confirmation"
    CONSULT_NOTE = "consult_note"
    SPECIALIST_COMPLETION_CONFIRMATION = "specialist_completion_confirmation"
    FHIR_TASK_UPDATE = "fhir_task_update"
    PATIENT_DECLINED = "patient_declined"
    SPECIALIST_DECLINED = "specialist_declined"
    CANCELLATION_NOTICE = "cancellation_notice"
    MESSAGE_DELIVERY = "message_delivery"
    PACKAGE_APPROVAL = "package_approval"


S = Status
E = Evidence

TERMINAL: frozenset[Status] = frozenset({S.COMPLETED, S.DECLINED, S.CANCELLED})

# Ordered progress line (the "route" drawn in the UI).
ROUTE: tuple[Status, ...] = (
    S.IMPORTED,
    S.NEEDS_REVIEW,
    S.READY,
    S.SUBMITTED,
    S.ACKNOWLEDGED,
    S.SCHEDULED,
    S.COMPLETED,
)

TRANSITIONS: dict[Status, frozenset[Status]] = {
    S.IMPORTED: frozenset({S.NEEDS_REVIEW}),
    S.NEEDS_REVIEW: frozenset({S.READY, S.EXCEPTION}),
    S.READY: frozenset({S.SUBMITTED, S.EXCEPTION}),
    S.SUBMITTED: frozenset({S.ACKNOWLEDGED, S.EXCEPTION, S.DECLINED, S.CANCELLED}),
    S.ACKNOWLEDGED: frozenset({S.SCHEDULED, S.EXCEPTION, S.DECLINED, S.CANCELLED}),
    S.SCHEDULED: frozenset({S.COMPLETED, S.EXCEPTION, S.DECLINED, S.CANCELLED}),
    S.EXCEPTION: frozenset({S.NEEDS_REVIEW}),
    S.COMPLETED: frozenset(),
    S.DECLINED: frozenset(),
    S.CANCELLED: frozenset(),
}

# Evidence kinds accepted for entering each state. ``None`` means no evidence needed.
ACCEPTED_EVIDENCE: dict[Status, frozenset[Evidence] | None] = {
    S.IMPORTED: None,
    S.NEEDS_REVIEW: None,
    S.READY: frozenset({E.PACKAGE_APPROVAL}),
    S.SUBMITTED: frozenset({E.TRANSMISSION_RECEIPT, E.MANUAL_SUBMISSION_NOTE}),
    S.ACKNOWLEDGED: frozenset(
        {E.SPECIALIST_ACKNOWLEDGMENT, E.PHONE_CONFIRMATION, E.FHIR_TASK_UPDATE}
    ),
    S.SCHEDULED: frozenset(
        {E.APPOINTMENT_RECORD, E.PHONE_CONFIRMATION, E.PATIENT_CONFIRMATION, E.FHIR_TASK_UPDATE}
    ),
    S.COMPLETED: frozenset(
        {E.CONSULT_NOTE, E.SPECIALIST_COMPLETION_CONFIRMATION, E.FHIR_TASK_UPDATE}
    ),
    S.EXCEPTION: None,
    S.DECLINED: frozenset(
        {E.PATIENT_DECLINED, E.SPECIALIST_DECLINED, E.PHONE_CONFIRMATION, E.FHIR_TASK_UPDATE}
    ),
    S.CANCELLED: frozenset(
        {E.CANCELLATION_NOTICE, E.PATIENT_DECLINED, E.PHONE_CONFIRMATION, E.FHIR_TASK_UPDATE}
    ),
}

REASON_REQUIRED: frozenset[Status] = frozenset({S.EXCEPTION, S.DECLINED, S.CANCELLED})


@dataclass(frozen=True)
class TransitionError:
    code: str
    message: str


def allowed_targets(current: Status) -> frozenset[Status]:
    return TRANSITIONS[current]


def check_transition(
    current: Status,
    target: Status,
    *,
    evidence_type: str | None = None,
    evidence_reference: str | None = None,
    reason: str | None = None,
    correction: bool = False,
) -> TransitionError | None:
    """Return ``None`` if the move is legal, otherwise the first rule it breaks."""
    if current == target:
        return TransitionError("no_change", f"Referral is already {current.value}.")

    if correction:
        if current not in TERMINAL:
            return TransitionError("not_terminal", "Corrections apply only to closed referrals.")
        if target != S.EXCEPTION:
            return TransitionError(
                "bad_correction", "A correction reopens a referral as an exception."
            )
        if not (reason and reason.strip()):
            return TransitionError(
                "reason_required", "Explain why this outcome is being corrected."
            )
        return None

    if target not in TRANSITIONS[current]:
        if current in TERMINAL:
            return TransitionError(
                "terminal", f"Referral is {current.value}; use a correction to reopen it."
            )
        return TransitionError(
            "invalid_transition", f"A referral can't move from {current.value} to {target.value}."
        )

    if target in REASON_REQUIRED and not (reason and reason.strip()):
        return TransitionError("reason_required", f"Give a reason for moving to {target.value}.")

    accepted = ACCEPTED_EVIDENCE[target]
    if accepted is not None:
        if not evidence_type or not (evidence_reference and evidence_reference.strip()):
            return TransitionError(
                "evidence_required", f"Moving to {target.value} needs supporting evidence."
            )
        try:
            kind = Evidence(evidence_type)
        except ValueError:
            return TransitionError("unknown_evidence", f"Unknown evidence type {evidence_type!r}.")
        if kind not in accepted:
            return TransitionError(
                "evidence_not_accepted",
                f"{kind.value} does not prove {target.value}. "
                f"Accepted: {', '.join(sorted(e.value for e in accepted))}.",
            )
    return None


def route_position(status: Status) -> int:
    """Index along the route; off-route states return -1."""
    return ROUTE.index(status) if status in ROUTE else -1
