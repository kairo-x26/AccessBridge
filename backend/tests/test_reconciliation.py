from __future__ import annotations

from app.integrations import simulated_ehr as ehr
from tests.factories import advance, make_org, make_user


def _setup(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    rid = client.post(
        "/v1/referrals/import",
        headers=coord.headers(),
        json={
            "bundle": ehr.bundle(ehr.SyntheticReferral("sr-9", ehr.JAMES, "Orthopedics", "Knee"))
        },
    ).json()["imported"][0]
    return coord, rid


def _send(client, coord, *resources):
    r = client.post(
        "/v1/integrations/fhir/task-updates",
        headers=coord.headers(),
        json={"resources": list(resources)},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _status(client, coord, rid):
    return client.get(f"/v1/referrals/{rid}", headers=coord.headers()).json()


def test_forward_updates_apply_with_evidence(client):
    coord, rid = _setup(client)
    advance(rid, "ready", "submitted")
    out = _send(
        client,
        coord,
        ehr.task_update("sr-9", "accepted", version=1),
        ehr.task_update("sr-9", "in-progress", version=2, appointment="2026-03-02T09:30:00-06:00"),
    )
    assert [o["outcome"] for o in out] == ["applied", "applied"]
    d = _status(client, coord, rid)
    assert d["status"] == "scheduled" and d["appointment_at"]
    assert d["events"][-1]["evidence_type"] == "fhir_task_update"


def test_skipping_ahead_applies_each_step(client):
    coord, rid = _setup(client)
    advance(rid, "ready", "submitted")
    out = _send(
        client,
        coord,
        ehr.task_update("sr-9", "completed", report_reference="DocumentReference/cn-1"),
    )
    assert out[0]["applied"] == ["acknowledged", "scheduled", "completed"]


def test_completion_without_report_needs_person(client):
    coord, rid = _setup(client)
    advance(rid, "ready", "submitted")
    out = _send(client, coord, ehr.task_update("sr-9", "completed"))
    assert out[0]["outcome"] == "review"
    d = _status(client, coord, rid)
    assert d["status"] == "scheduled"
    assert any(t["kind"] == "reconciliation" for t in d["tasks"])


def test_duplicates_and_stale_updates(client):
    coord, rid = _setup(client)
    advance(rid, "ready", "submitted", "acknowledged", "scheduled")
    acc = ehr.task_update("sr-9", "accepted", version=1)
    assert _send(client, coord, acc)[0]["outcome"] == "stale"
    assert _send(client, coord, acc)[0]["outcome"] == "duplicate"
    assert _status(client, coord, rid)["status"] == "scheduled"


def test_update_before_submission_is_conflict(client):
    coord, rid = _setup(client)
    out = _send(client, coord, ehr.task_update("sr-9", "accepted"))
    assert out[0]["outcome"] == "conflict"
    assert _status(client, coord, rid)["status"] == "needs_review"


def test_terminal_and_exception_states_are_not_overwritten(client):
    coord, rid = _setup(client)
    advance(rid, "ready", "submitted", "acknowledged", "scheduled", "completed")
    out = _send(client, coord, ehr.task_update("sr-9", "cancelled", version=7))
    assert out[0]["outcome"] == "conflict"
    assert _status(client, coord, rid)["status"] == "completed"


def test_rejection_declines_and_unknown_is_reported(client):
    coord, rid = _setup(client)
    advance(rid, "ready", "submitted")
    out = _send(
        client,
        coord,
        ehr.task_update("sr-9", "rejected", note="Out of network"),
        ehr.task_update("nope", "accepted"),
        {"resourceType": "Task"},
    )
    assert [o["outcome"] for o in out] == ["applied", "unmatched", "invalid"]
    assert _status(client, coord, rid)["status"] == "declined"
