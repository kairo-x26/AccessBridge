from __future__ import annotations

import itertools

import pytest

from app.domain.state_machine import (
    ACCEPTED_EVIDENCE,
    TERMINAL,
    TRANSITIONS,
    Evidence,
    Status,
    check_transition,
)

S = Status
SPEC_EDGES = {
    (S.IMPORTED, S.NEEDS_REVIEW),
    (S.NEEDS_REVIEW, S.READY),
    (S.READY, S.SUBMITTED),
    (S.SUBMITTED, S.ACKNOWLEDGED),
    (S.ACKNOWLEDGED, S.SCHEDULED),
    (S.SCHEDULED, S.COMPLETED),
    (S.NEEDS_REVIEW, S.EXCEPTION),
    (S.READY, S.EXCEPTION),
    (S.SUBMITTED, S.EXCEPTION),
    (S.ACKNOWLEDGED, S.EXCEPTION),
    (S.SCHEDULED, S.EXCEPTION),
    (S.EXCEPTION, S.NEEDS_REVIEW),
    *(
        (a, b)
        for a in (S.SUBMITTED, S.ACKNOWLEDGED, S.SCHEDULED)
        for b in (S.DECLINED, S.CANCELLED)
    ),
}


def _good_args(target: Status) -> dict:
    accepted = ACCEPTED_EVIDENCE[target]
    return {
        "evidence_type": sorted(accepted)[0].value if accepted else None,
        "evidence_reference": "ref-1" if accepted else None,
        "reason": "because",
    }


def test_transition_table_matches_spec_diagram():
    edges = {(a, b) for a, targets in TRANSITIONS.items() for b in targets}
    assert edges == SPEC_EDGES


@pytest.mark.parametrize(("a", "b"), list(itertools.product(Status, Status)))
def test_every_pair(a, b):
    err = check_transition(a, b, **_good_args(b))
    if (a, b) in SPEC_EDGES:
        assert err is None, err
    else:
        assert err is not None


@pytest.mark.parametrize("target", [t for t in Status if ACCEPTED_EVIDENCE[t]])
def test_progress_states_need_evidence(target):
    source = next(a for a, b in SPEC_EDGES if b == target)
    err = check_transition(source, target, reason="r")
    assert err and err.code == "evidence_required"


def test_completion_rejects_message_delivery_and_patient_reply():
    for ev in (Evidence.MESSAGE_DELIVERY, Evidence.PATIENT_CONFIRMATION):
        err = check_transition(
            S.SCHEDULED, S.COMPLETED, evidence_type=ev.value, evidence_reference="msg-1"
        )
        assert err and err.code == "evidence_not_accepted"
    assert (
        check_transition(
            S.SCHEDULED, S.COMPLETED, evidence_type="consult_note", evidence_reference="doc-1"
        )
        is None
    )


def test_exception_requires_reason():
    err = check_transition(S.NEEDS_REVIEW, S.EXCEPTION)
    assert err and err.code == "reason_required"
    assert check_transition(S.NEEDS_REVIEW, S.EXCEPTION, reason="   ") is not None


def test_blank_evidence_reference_rejected():
    err = check_transition(
        S.READY, S.SUBMITTED, evidence_type="transmission_receipt", evidence_reference="  "
    )
    assert err and err.code == "evidence_required"


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
def test_terminal_requires_correction(terminal):
    err = check_transition(terminal, S.EXCEPTION, reason="oops")
    assert err and err.code == "terminal"
    assert check_transition(terminal, S.EXCEPTION, reason="oops", correction=True) is None
    assert check_transition(terminal, S.NEEDS_REVIEW, reason="x", correction=True) is not None
    assert check_transition(terminal, S.EXCEPTION, correction=True).code == "reason_required"


def test_correction_only_for_terminal():
    err = check_transition(S.SUBMITTED, S.EXCEPTION, reason="x", correction=True)
    assert err and err.code == "not_terminal"


def test_unknown_evidence_type():
    err = check_transition(S.READY, S.SUBMITTED, evidence_type="vibes", evidence_reference="x")
    assert err and err.code == "unknown_evidence"
