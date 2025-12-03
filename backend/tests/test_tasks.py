from __future__ import annotations

from datetime import timedelta

from app.core import db
from app.core.db import utcnow
from app.models import Task
from app.services import tasks
from tests.factories import make_org, make_user


def test_ensure_task_is_idempotent_by_key(database):
    org = make_org()
    with db.session_factory()() as s:
        a, created_a = tasks.ensure_task(
            s,
            organization_id=org,
            kind="missing_info",
            title="Need insurance",
            created_by="system:t",
            dedupe_key="k",
        )
        b, created_b = tasks.ensure_task(
            s,
            organization_id=org,
            kind="missing_info",
            title="Need insurance",
            created_by="system:t",
            dedupe_key="k",
        )
        assert created_a and not created_b and a.id == b.id
        tasks.resolve(s, a, actor="user:x", resolution="done")
        c, created_c = tasks.ensure_task(
            s,
            organization_id=org,
            kind="missing_info",
            title="Need insurance",
            created_by="system:t",
            dedupe_key="k",
        )
        assert created_c and c.id != a.id


def test_escalation_steps_priority_once_per_day(database):
    org = make_org()
    with db.session_factory()() as s:
        t, _ = tasks.ensure_task(
            s,
            organization_id=org,
            kind="follow_up",
            title="Call",
            created_by="system:t",
            due_at=utcnow() - timedelta(hours=1),
        )
        assert [x.id for x in tasks.escalate_overdue(s)] == [t.id]
        assert t.priority == "high" and t.escalation_level == 1
        assert tasks.escalate_overdue(s) == []
        later = utcnow() + timedelta(days=1, minutes=1)
        tasks.escalate_overdue(s, now=later)
        tasks.escalate_overdue(s, now=later + timedelta(days=1, minutes=1))
        assert t.priority == "urgent" and t.escalation_level == 3
        s.commit()


def test_task_api_create_list_assign_resolve(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    nav = make_user(org, "navigator")
    h = coord.headers()
    low = client.post("/v1/tasks", headers=h, json={"title": "File", "priority": "low"}).json()
    urgent = client.post(
        "/v1/tasks",
        headers=h,
        json={"title": "Call patient", "priority": "urgent", "kind": "patient_assistance"},
    ).json()
    items = client.get("/v1/tasks", headers=h).json()["items"]
    assert [i["id"] for i in items] == [urgent["id"], low["id"]]
    r = client.patch(f"/v1/tasks/{low['id']}", headers=h, json={"owner_id": nav.user_id})
    assert r.json()["owner_id"] == nav.user_id
    assert client.get("/v1/tasks?owner=me", headers=nav.headers()).json()["total"] == 1
    missing = client.patch(f"/v1/tasks/{low['id']}", headers=h, json={"status": "done"})
    assert missing.status_code == 422
    done = client.patch(
        f"/v1/tasks/{low['id']}", headers=h, json={"status": "done", "resolution": "Filed"}
    ).json()
    assert done["status"] == "done" and done["resolved_at"]
    assert client.get("/v1/tasks?status=closed", headers=h).json()["total"] == 1
    assert (
        client.post("/v1/tasks", headers=h, json={"title": "x", "kind": "nope"}).status_code == 422
    )


def test_task_cross_tenant(client):
    a, b = make_org("a", "A"), make_org("b", "B")
    ca, cb = make_user(a, "coordinator"), make_user(b, "coordinator")
    t = client.post("/v1/tasks", headers=ca.headers(), json={"title": "x"}).json()
    assert (
        client.patch(
            f"/v1/tasks/{t['id']}", headers=cb.headers(), json={"priority": "high"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/tasks", headers=ca.headers(), json={"title": "x", "owner_id": cb.user_id}
        ).status_code
        == 404
    )


def test_clinician_cannot_see_tasks(client):
    org = make_org()
    assert client.get("/v1/tasks", headers=make_user(org, "clinician").headers()).status_code == 403


def test_terminal_transition_closes_open_tasks(database):
    org = make_org()
    from app.integrations import simulated_ehr as ehr
    from app.services import referrals
    from app.services.referrals import IntakeRecord, PatientIn

    with db.session_factory()() as s:
        p = ehr.ROSA
        res = referrals.ingest(
            s,
            org,
            IntakeRecord("fhir", "x1", PatientIn(p.mrn, p.given, p.family), "cardiology"),
            actor="system:t",
        )
        r = res.referral
        tasks.ensure_task(
            s,
            organization_id=org,
            referral_id=r.id,
            kind="follow_up",
            title="t",
            created_by="system:t",
        )
        for st, ev in [("ready", "package_approval"), ("submitted", "transmission_receipt")]:
            referrals.transition(
                s, r, st, actor="system:t", evidence_type=ev, evidence_reference="e"
            )
        referrals.transition(
            s,
            r,
            "cancelled",
            actor="system:t",
            evidence_type="cancellation_notice",
            evidence_reference="e",
            reason="patient moved",
        )
        open_tasks = (
            s.query(Task)
            .filter(Task.referral_id == r.id, Task.status.in_(tasks.OPEN_STATES))
            .count()
        )
        assert open_tasks == 0
