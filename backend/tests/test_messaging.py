from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest

from app.core import db
from app.core.db import utcnow
from app.domain import templates as T
from app.integrations import sms
from app.models import Organization, Referral
from app.services.response_classifier import classify_rules
from app.workers import queue
from tests import flows
from tests.factories import make_user


@pytest.fixture(autouse=True)
def _fresh_gateway():
    sms.gateway = sms.SimulatedGateway()
    yield


def _hook(client, payload: dict, ts: int | None = None, tamper=False):
    raw = json.dumps(payload).encode()
    headers = sms.sign(raw, ts)
    if tamper:
        headers["x-ab-signature"] = "0" * 64
    return client.post(
        "/v1/webhooks/messaging",
        content=raw,
        headers={**headers, "content-type": "application/json"},
    )


# --- templates ---------------------------------------------------------------------------


def test_template_rules():
    assert T.problems(T.BUILTIN[("schedule_prompt", "en")]) == []
    assert any("placeholders" in p for p in T.problems("Hi {ssn}. Reply STOP to opt out."))
    assert any("opt-out" in p for p in T.problems("Hi {first_name}, call us."))
    assert any(
        "administrative" in p
        for p in T.problems("Your test results are ready. Reply STOP to opt out.")
    )
    assert T.render("Hi {first_name}", {"first_name": "Rosa"}) == "Hi Rosa"


def test_four_eyes_template_review(client):
    org, admin, coord, _ = flows.setup_clinic(client)
    t = client.put(
        "/v1/templates/schedule_prompt/en",
        headers=admin.headers(),
        json={"body": T.BUILTIN[("schedule_prompt", "en")]},
    ).json()
    assert t["active"] is False
    assert (
        client.post(f"/v1/templates/{t['id']}/review", headers=admin.headers()).status_code == 403
    )
    assert (
        client.post(f"/v1/templates/{t['id']}/review", headers=coord.headers()).status_code == 403
    )  # coordinators can't manage templates
    other = make_user(org, "admin", email="second.admin@example.org")
    ok = client.post(f"/v1/templates/{t['id']}/review", headers=other.headers()).json()
    assert ok["active"] and ok["reviewed_by"] == f"user:{other.user_id}"
    listed = client.get("/v1/templates", headers=coord.headers()).json()
    assert any(x["builtin"] and x["language"] == "es" for x in listed)
    bad = client.put(
        "/v1/templates/schedule_prompt/en",
        headers=admin.headers(),
        json={"body": "Hi {first_name}, your diagnosis is ready."},
    )
    assert bad.status_code == 422


# --- sending ------------------------------------------------------------------------------


def test_send_checks_suppress_and_explain(client):
    org, admin, coord, prov, rid = flows.submitted_referral(client)
    h = coord.headers()
    pre = client.post(
        f"/v1/referrals/{rid}/communications/preview",
        headers=h,
        json={"template_key": "schedule_prompt"},
    ).json()
    assert not pre["can_send"]
    assert {
        "No consent to text messages on record.",
        "Patient contact details aren't verified.",
    } <= set(pre["problems"])
    assert any("Spanish" in p for p in pre["problems"])  # Rosa prefers Spanish
    assert (
        client.post(
            f"/v1/referrals/{rid}/communications",
            headers=h,
            json={"template_key": "schedule_prompt"},
        ).status_code
        == 422
    )


def test_send_in_patients_language(client):
    org, admin, coord, prov, rid = flows.submitted_referral(client)
    flows.adopt_templates(client, org, admin)
    flows.consent(client, coord, rid)
    h = coord.headers()
    r = client.post(
        f"/v1/referrals/{rid}/communications", headers=h, json={"template_key": "schedule_prompt"}
    )
    assert r.status_code == 201, r.text
    msg = r.json()
    assert msg["status"] == "sent" and msg["language"] == "es"
    assert msg["body"].startswith("Hola Rosa") and "Prairie Heart Associates" in msg["body"]
    assert "Palpitations" not in msg["body"]  # never clinical content
    assert sms.gateway.outbox[-1]["to"] == "+1 555 010 2231"
    again = client.post(
        f"/v1/referrals/{rid}/communications/preview",
        headers=h,
        json={"template_key": "schedule_prompt"},
    ).json()
    assert "already sent in the last 3 days" in " ".join(again["problems"])
    # Delivery receipt, then a duplicate of the same event.
    ev = {
        "type": "delivery",
        "event_id": "ev-1",
        "message_id": sms.gateway.outbox[-1]["id"],
        "status": "delivered",
    }
    assert _hook(client, ev).json()["result"] == "applied"
    assert _hook(client, ev).json()["result"] == "duplicate"
    msgs = client.get(f"/v1/referrals/{rid}/communications", headers=h).json()
    assert msgs[-1]["status"] == "delivered"


def test_invalid_number_and_outage(client):
    org, admin, coord, prov, rid = flows.submitted_referral(client)
    flows.adopt_templates(client, org, admin)
    flows.consent(client, coord, rid, phone="+1 555 010 9999")
    flows.consent(client, coord, rid)  # re-verify after the number change
    h = coord.headers()
    r = client.post(
        f"/v1/referrals/{rid}/communications", headers=h, json={"template_key": "schedule_prompt"}
    )
    assert r.status_code == 503
    assert client.get(f"/v1/referrals/{rid}/communications", headers=h).json() == []
    flows.consent(client, coord, rid, phone="+1 555 010 0000")
    flows.consent(client, coord, rid)
    bad = client.post(
        f"/v1/referrals/{rid}/communications", headers=h, json={"template_key": "schedule_prompt"}
    ).json()
    assert bad["status"] == "failed"
    d = client.get(f"/v1/referrals/{rid}", headers=h).json()
    assert d["patient"]["contact_verified"] is False
    assert any(t["title"] == "Patient phone number doesn't work" for t in d["tasks"])


# --- webhooks and replies -------------------------------------------------------------------


def test_webhook_signature_and_replay_window(client):
    flows.setup_clinic(client)
    ev = {"type": "inbound", "event_id": "x", "account": "riverbend", "from": "1", "body": "1"}
    assert _hook(client, ev, tamper=True).status_code == 401
    assert _hook(client, ev, ts=int(time.time()) - 3600).status_code == 401
    assert client.post("/v1/webhooks/messaging", content=b"{}").status_code == 401


@pytest.mark.parametrize(
    ("text", "category", "escalate"),
    [
        ("1", "confirmed", False),
        ("Sí, tengo cita el martes", "confirmed", False),
        ("2 I need a ride", "needs_assistance", False),
        ("necesito ayuda con transporte", "needs_assistance", False),
        ("3", "declined", False),
        ("STOP", "opt_out", False),
        ("yes but my chest pain is worse", "unknown", True),
        ("should I stop taking my pills?", "unknown", True),
        ("tengo dolor de pecho", "unknown", True),
        ("who is this?", "unknown", False),
    ],
)
def test_classifier(text, category, escalate):
    c = classify_rules(text)
    assert (c.category, c.escalate) == (category, escalate)


def _sent_referral(client):
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    flows.adopt_templates(client, org, admin)
    flows.consent(client, coord, rid)
    client.post(
        f"/v1/referrals/{rid}/communications",
        headers=coord.headers(),
        json={"template_key": "schedule_prompt"},
    )
    return org, admin, coord, rid


def _reply(client, body, phone="+1 555 010 2231", event_id=None):
    return _hook(
        client,
        {
            "type": "inbound",
            "event_id": event_id or f"in-{time.time_ns()}",
            "account": "riverbend",
            "from": phone,
            "body": body,
        },
    ).json()


def test_confirmed_reply_needs_approval_to_schedule(client):
    org, admin, coord, rid = _sent_referral(client)
    assert _reply(client, "1")["result"] == "applied"
    queue.run_pending()
    h = coord.headers()
    assert client.get(f"/v1/referrals/{rid}", headers=h).json()["status"] == "acknowledged"
    pending = [
        a
        for a in client.get("/v1/approvals", headers=h).json()
        if a["action"]["tool"] == "record_scheduled"
    ]
    assert len(pending) == 1
    client.post(
        f"/v1/approvals/{pending[0]['id']}/decision", headers=h, json={"decision": "approved"}
    )
    queue.run_pending()
    d = client.get(f"/v1/referrals/{rid}", headers=h).json()
    assert d["status"] == "scheduled"
    assert d["events"][-1]["evidence_type"] == "patient_confirmation"
    assert d["events"][-1]["evidence_reference"].startswith("message:")


def test_help_stop_and_urgent_replies(client):
    org, admin, coord, rid = _sent_referral(client)
    h = coord.headers()
    _reply(client, "2 - I don't have a ride")
    _reply(client, "my chest hurts, should I still go?")
    tasks = client.get(f"/v1/tasks?referral_id={rid}", headers=h).json()["items"]
    assert any(t["title"] == "Patient asked for help" and t["priority"] == "high" for t in tasks)
    assert any(
        t["title"] == "Patient reply needs clinical staff" and t["priority"] == "urgent"
        for t in tasks
    )
    inbox = client.get("/v1/communications/inbox", headers=h).json()
    assert inbox[0]["escalated"] is True  # escalations first
    _reply(client, "STOP")
    d = client.get(f"/v1/referrals/{rid}", headers=h).json()
    assert d["patient"]["opted_out"] is True
    pre = client.post(
        f"/v1/referrals/{rid}/communications/preview",
        headers=h,
        json={"template_key": "appointment_check"},
    ).json()
    assert "Patient opted out of text messages." in pre["problems"]


def test_shared_phone_and_unknown_sender(client):
    org, admin, coord, rid = _sent_referral(client)
    # A second patient with the same phone number got a message too.
    from app.integrations import simulated_ehr as ehr

    sib = ehr.SyntheticPatient(
        "100999", "Ana", "Delgado", "2001-01-01", "+1 555 010 2231", language="es"
    )
    ref = ehr.SyntheticReferral(
        "sr-sib",
        sib,
        "Cardiology",
        "x",
        performer_ref="NPI-PHA",
        performer="Prairie Heart Associates",
    )
    rid2 = client.post(
        "/v1/referrals/import", headers=coord.headers(), json={"bundle": ehr.bundle(ref)}
    ).json()["imported"][0]
    with db.session_factory()() as s:
        r2 = s.get(Referral, rid2)
        r2.status = "acknowledged"
        s.commit()
    flows.consent(client, coord, rid2)
    client.post(
        f"/v1/referrals/{rid2}/communications",
        headers=coord.headers(),
        json={"template_key": "schedule_prompt"},
    )
    assert _reply(client, "1")["result"] == "identity_uncertain"
    assert _reply(client, "1", phone="+1 555 777 1212")["result"] == "unmatched_sender"
    queue.run_pending()
    assert not [
        a
        for a in client.get("/v1/approvals", headers=coord.headers()).json()
        if a["action"]["tool"] == "record_scheduled"
    ]


def test_follow_up_outreach_requires_approval_unless_preauthorized(client):
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    flows.adopt_templates(client, org, admin)
    flows.consent(client, coord, rid)
    with db.session_factory()() as s:
        s.get(Referral, rid).status_changed_at = utcnow() - timedelta(days=6)
        s.commit()
    from app.workers.run import schedule_sweeps

    schedule_sweeps()
    queue.run_pending()
    h = coord.headers()
    sends = [
        a
        for a in client.get("/v1/approvals", headers=h).json()
        if a["action"]["tool"] == "send_patient_message"
    ]
    assert len(sends) == 1 and not sms.gateway.outbox
    # Reject it, then pre-authorize the reminder for low-risk follow-up.
    client.post(
        f"/v1/approvals/{sends[0]['id']}/decision",
        headers=h,
        json={"decision": "rejected", "reason": "Called instead"},
    )
    with db.session_factory()() as s:
        s.get(Organization, org).configuration = {
            "preauthorized_tools": ["send_patient_message"],
            "preauthorized_templates": ["schedule_prompt"],
        }
        r = s.get(Referral, rid)
        r.version += 1  # state moved on (e.g. a note was added)
        s.commit()
    schedule_sweeps(utcnow() + timedelta(hours=1))
    queue.run_pending()
    assert len(sms.gateway.outbox) == 1


def test_workflow_c_completion_with_consult_note(client):
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    h = coord.headers()
    from app.integrations import simulated_ehr as ehr

    client.post(
        "/v1/integrations/fhir/task-updates",
        headers=h,
        json={
            "resources": [
                ehr.task_update(
                    "sr-1", "in-progress", version=2, appointment="2026-04-02T09:00:00-05:00"
                )
            ]
        },
    )
    assert client.get(f"/v1/referrals/{rid}", headers=h).json()["status"] == "scheduled"
    note = (
        b"Prairie Heart Associates - Consultation Note\nPatient Name: Rosa Delgado\n"
        b"DOB: 1968-03-14\nThank you for this referral. Seen in clinic today.\n"
        b"Recommendations: follow up with PCP."
    )
    up = client.post(
        f"/v1/referrals/{rid}/documents",
        headers=h,
        files={"file": ("consult.txt", note, "text/plain")},
    )
    assert up.status_code == 201
    queue.run_pending()
    pend = [
        a
        for a in client.get("/v1/approvals", headers=h).json()
        if a["action"]["tool"] == "propose_completion"
    ]
    assert len(pend) == 1
    assert client.get(f"/v1/referrals/{rid}", headers=h).json()["status"] == "scheduled"
    client.post(f"/v1/approvals/{pend[0]['id']}/decision", headers=h, json={"decision": "approved"})
    queue.run_pending()
    d = client.get(f"/v1/referrals/{rid}", headers=h).json()
    assert d["status"] == "completed"
    assert d["events"][-1]["evidence_type"] == "consult_note"
    clinician = make_user(org, "clinician")
    notes = client.get("/v1/notifications", headers=clinician.headers()).json()
    assert notes and notes[0]["kind"] == "care_completed" and not notes[0]["read"]
    client.post(f"/v1/notifications/{notes[0]['id']}/read", headers=clinician.headers())
    assert (
        client.get("/v1/notifications?unread_only=true", headers=clinician.headers()).json() == []
    )


def test_consult_note_for_another_patient_is_not_completed(client):
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    h = coord.headers()
    from app.integrations import simulated_ehr as ehr

    client.post(
        "/v1/integrations/fhir/task-updates",
        headers=h,
        json={
            "resources": [
                ehr.task_update("sr-1", "in-progress", version=2, business_status="scheduled")
            ]
        },
    )
    note = (
        b"Consultation note\nPatient Name: Rosa Delgado\nDOB: 1971-09-09\n"
        b"Thank you for this referral."
    )
    client.post(
        f"/v1/referrals/{rid}/documents",
        headers=h,
        files={"file": ("consult.txt", note, "text/plain")},
    )
    queue.run_pending()
    assert not [
        a
        for a in client.get("/v1/approvals", headers=h).json()
        if a["action"]["tool"] == "propose_completion"
    ]
    tasks = client.get(f"/v1/tasks?referral_id={rid}", headers=h).json()["items"]
    assert any("another patient" in t["title"] for t in tasks)


def test_early_consult_note_asks_to_record_appointment(client):
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    h = coord.headers()
    note = (
        b"Consultation note\nPatient Name: Rosa Delgado\nDOB: 1968-03-14\n"
        b"Thank you for this referral."
    )
    client.post(
        f"/v1/referrals/{rid}/documents",
        headers=h,
        files={"file": ("consult.txt", note, "text/plain")},
    )
    queue.run_pending()
    tasks = client.get(f"/v1/tasks?referral_id={rid}", headers=h).json()["items"]
    assert any(t["title"].startswith("Consult note received") for t in tasks)
    assert client.get(f"/v1/referrals/{rid}", headers=h).json()["status"] == "acknowledged"
