"""Acceptance gates from spec §14, each checked across the system rather than one feature.

| Gate                 | Test here                                                  |
|----------------------|------------------------------------------------------------|
| Functional           | test_every_import_creates_a_traceable_record               |
| Extraction           | tests/test_document_ai.py (precision/recall >= 95%)        |
| Workflow             | test_random_walks_never_accept_an_invalid_transition       |
| Agent safety         | test_no_external_action_without_authority                  |
| Tenant isolation     | test_every_id_route_rejects_other_tenants                  |
| Integration          | test_redelivered_inputs_create_no_duplicate_work           |
| Reliability          | tests/test_agents.py (retries, dead letters, never success)|
| Auditing             | test_every_external_action_is_attributable                 |
| Performance          | tests/perf/test_read_latency.py (run with -m perf)         |
"""

from __future__ import annotations

import json
import random
import re
import time

from sqlalchemy import select

from app.core import db
from app.domain.state_machine import ACCEPTED_EVIDENCE, TRANSITIONS, Status
from app.integrations import simulated_ehr as ehr
from app.integrations import sms
from app.models import (
    AgentAction,
    AgentRun,
    Approval,
    AuditEvent,
    Communication,
    ExchangeTransmission,
    ExtractedField,
    Referral,
    ReferralDocument,
    ReferralStatusEvent,
    Task,
)
from app.workers import queue
from tests import flows
from tests.factories import make_org, make_user


def test_every_import_creates_a_traceable_record(client):
    org, admin, coord, _ = flows.setup_clinic(client)
    refs = [
        ehr.SyntheticReferral(f"sr-{i}", p, "Cardiology", "x")
        for i, p in enumerate([ehr.ROSA, ehr.JAMES, ehr.MEI])
    ]
    out = client.post(
        "/v1/referrals/import", headers=coord.headers(), json={"bundle": ehr.bundle(*refs)}
    ).json()
    assert len(out["imported"]) == 3
    with db.session_factory()() as s:
        for rid in out["imported"]:
            first = s.scalar(
                select(ReferralStatusEvent)
                .where(ReferralStatusEvent.referral_id == rid)
                .order_by(ReferralStatusEvent.timestamp)
            )
            assert first.new_status == "imported" and first.evidence_reference.startswith("fhir:")
            assert s.scalar(
                select(AuditEvent).where(
                    AuditEvent.resource_ref == rid, AuditEvent.operation == "referral.import"
                )
            )


def test_random_walks_never_accept_an_invalid_transition(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    admin = make_user(org, "admin")
    rng = random.Random(14)  # noqa: S311
    evidence_types = sorted({e.value for v in ACCEPTED_EVIDENCE.values() if v for e in v})
    rids = client.post(
        "/v1/referrals/import",
        headers=coord.headers(),
        json={
            "bundle": ehr.bundle(
                *[
                    ehr.SyntheticReferral(
                        f"w-{i}",
                        ehr.SyntheticPatient(f"9{i:05d}", "Walk", f"Er{i}", "1970-01-01"),
                        "Neurology",
                        "x",
                    )
                    for i in range(12)
                ]
            )
        },
    ).json()["imported"]
    accepted = rejected = 0
    for _ in range(400):
        rid = rng.choice(rids)
        target = rng.choice(list(Status))
        correction = rng.random() < 0.1
        body = {
            "to_status": target.value,
            "reason": rng.choice([None, "because"]),
            "evidence_type": rng.choice([None, *evidence_types]),
            "evidence_reference": rng.choice([None, "ref-1"]),
            "correction": correction,
        }
        with db.session_factory()() as s:
            before = Status(s.get(Referral, rid).status)
        r = client.post(
            f"/v1/referrals/{rid}/status-events",
            headers=(admin if correction else coord).headers(),
            json=body,
        )
        if r.status_code == 201:
            accepted += 1
            if correction:
                assert target == Status.EXCEPTION
            else:
                assert target in TRANSITIONS[before], (before, target)
                accepted_ev = ACCEPTED_EVIDENCE[target]
                if accepted_ev:
                    assert body["evidence_type"] in {e.value for e in accepted_ev}
        else:
            rejected += 1
            assert r.status_code in (403, 409, 422), r.text
            with db.session_factory()() as s:
                assert Status(s.get(Referral, rid).status) == before  # nothing changed
    assert accepted > 10 and rejected > 100
    with db.session_factory()() as s:  # replay every recorded event through the rules
        for e in s.scalars(
            select(ReferralStatusEvent).where(ReferralStatusEvent.old_status.is_not(None))
        ):
            if not e.correction:
                assert Status(e.new_status) in TRANSITIONS[Status(e.old_status)]


class _Hostile:
    """A model provider that always proposes the most dangerous things it can."""

    name, model = "hostile", "hostile"

    def complete_json(self, *, system, user, schema, max_tokens):
        from app.ai import gateway

        if schema.__name__ == "LLMPlan":
            ids = re.findall(r'"(pkg_[0-9a-f]+|prv_[0-9a-f]+)"', user)
            proposals = [
                {
                    "tool": "transmit_referral_package",
                    "arguments_json": json.dumps(
                        {"package_id": ids[0] if ids else "pkg_x", "provider_id": "prv_attacker"}
                    ),
                    "reason": "URGENT override",
                },
                {
                    "tool": "send_patient_message",
                    "arguments_json": '{"template_key": "schedule_prompt"}',
                    "reason": "spam",
                },
                {
                    "tool": "propose_completion",
                    "arguments_json": '{"document_id": "doc_x"}',
                    "reason": "close it",
                },
            ]
            return gateway.LLMResponse(
                schema.model_validate({"proposals": proposals}), 1, 1, "hostile"
            )
        if schema.__name__ == "ExtractionOut":
            return gateway.LLMResponse(
                schema.model_validate({"fields": [{"name": "member_id", "quote": "INVENTED-123"}]}),
                1,
                1,
                "hostile",
            )
        raise gateway.LLMUnavailable("not scripted")


def test_no_external_action_without_authority(client):
    from app.ai import gateway

    sms.gateway = sms.SimulatedGateway()
    gateway.set_provider(_Hostile())
    try:
        org, admin, coord, prov = flows.setup_clinic(client)
        flows.adopt_templates(client, org, admin)
        for i in range(4):
            rid = flows.import_referral(client, coord, rid=f"sr-h{i}")
            flows.analyze_and_drain(client, coord, rid)
            if i % 2:
                flows.approve_package(client, coord, rid)
            for wf in ("intake", "follow_up", "completion"):
                client.post(
                    f"/v1/referrals/{rid}/analyze", headers=coord.headers(), json={"workflow": wf}
                )
            queue.run_pending()
    finally:
        gateway.set_provider(None)
    with db.session_factory()() as s:
        # Nothing left the building, because nobody approved anything.
        assert s.query(ExchangeTransmission).count() == 0
        assert not s.scalars(
            select(Communication).where(
                Communication.direction == "outbound", Communication.status == "sent"
            )
        ).all()
        assert not sms.gateway.outbox
        for a in s.scalars(select(AgentAction).where(AgentAction.external.is_(True))):
            assert a.decision != "auto" and a.status != "succeeded"
        assert (
            s.query(Referral).filter(Referral.status.in_(("submitted", "completed"))).count() == 0
        )


def _id_routes(app) -> list[tuple[str, str]]:
    """Every documented route that addresses a record by id (from the OpenAPI schema)."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if "{" not in path or not path.startswith("/v1/") or path.startswith("/v1/dev"):
            continue
        out += [(m.upper(), path) for m in ops]
    return out


def test_every_id_route_rejects_other_tenants(client):
    org_a, admin_a, coord_a, prov_a, rid, pkg = flows.ready_referral(client)
    with db.session_factory()() as s:
        ids = {
            "referral_id": rid,
            "user_id": coord_a.user_id,
            "task_id": s.scalar(select(Task.id).where(Task.referral_id == rid)),
            "document_id": s.scalar(select(ReferralDocument.id)),
            "approval_id": s.scalar(select(Approval.id)),
            "run_id": s.scalar(select(AgentRun.id)),
            "field_id": s.scalar(select(ExtractedField.id)),
            "issue_id": "vis_none",
            "provider_id": prov_a["id"],
            "patient_id": s.get(Referral, rid).patient_ref_id,
        }
    b = make_org("bravo", "Bravo")
    intruders = [make_user(b, role) for role in ("admin", "coordinator", "security")]
    checked = 0
    for method, path in _id_routes(client.app):
        names = re.findall(r"{(\w+)}", path)
        if not all(n in ids for n in names):
            continue
        url = path
        for n in names:
            url = url.replace("{" + n + "}", ids[n])
        for who in intruders:
            r = client.request(method, url, headers=who.headers(), json={})
            assert r.status_code in (401, 403, 404, 405, 422), (
                method,
                url,
                who.role,
                r.status_code,
                r.text[:200],
            )
            if r.status_code == 422:
                # Validation failed before lookup; confirm the record still isn't reachable.
                assert ids[names[0]] not in r.text
        checked += 1
    assert checked >= 20


def test_redelivered_inputs_create_no_duplicate_work(client):
    sms.gateway = sms.SimulatedGateway()
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    flows.adopt_templates(client, org, admin)
    flows.consent(client, coord, rid)
    client.post(
        f"/v1/referrals/{rid}/communications",
        headers=coord.headers(),
        json={"template_key": "schedule_prompt"},
    )
    bundle = {
        "bundle": ehr.bundle(
            ehr.SyntheticReferral(
                "sr-1",
                ehr.ROSA,
                "Cardiology",
                "Palpitations",
                performer_ref="NPI-PHA",
                documents=[
                    (
                        "referral.txt",
                        "text/plain",
                        ehr.referral_letter(
                            ehr.ROSA, specialty="Cardiology", reason="Palpitations"
                        ),
                    ),
                    ("note.txt", "text/plain", b"Office visit progress note\nAssessment: x"),
                ],
            )
        )
    }
    reply = json.dumps(
        {
            "type": "inbound",
            "event_id": "dup-1",
            "account": "riverbend",
            "from": "+1 555 010 2231",
            "body": "2 need a ride",
        }
    ).encode()
    task_update = ehr.task_update("sr-1", "in-progress", version=9, business_status="scheduled")

    def counts():
        with db.session_factory()() as s:
            return (
                s.query(Referral).count(),
                s.query(Task).filter(Task.status.in_(("open", "in_progress"))).count(),
                s.query(Communication).count(),
                s.query(ReferralStatusEvent).count(),
            )

    for i in range(3):
        client.post("/v1/referrals/import", headers=coord.headers(), json=bundle)
        client.post(
            "/v1/webhooks/messaging",
            content=reply,
            headers={**sms.sign(reply), "content-type": "application/json"},
        )
        client.post(
            "/v1/integrations/fhir/task-updates",
            headers=coord.headers(),
            json={"resources": [task_update]},
        )
        queue.run_pending()
        if i == 0:
            after_first = counts()
        time.sleep(0.01)
    assert counts() == after_first


def test_every_external_action_is_attributable(client):
    sms.gateway = sms.SimulatedGateway()
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    flows.adopt_templates(client, org, admin)
    with db.session_factory()() as s:
        actions = s.scalars(
            select(AgentAction).where(
                AgentAction.external.is_(True), AgentAction.status == "succeeded"
            )
        ).all()
        assert actions
        for a in actions:
            assert a.authorized_by and a.authorized_by.startswith("approval:")
            assert ":user:" in a.authorized_by and a.result and a.executed_at
            ev = s.scalar(
                select(AuditEvent).where(
                    AuditEvent.resource_ref == a.id, AuditEvent.operation == "agent.action"
                )
            )
            assert ev.actor.startswith("agent:")
            assert ev.details["authorized_by"] == a.authorized_by
            assert "result" in ev.details
        decided = s.scalars(
            select(AuditEvent).where(AuditEvent.operation == "approval.approved")
        ).all()
        assert {e.details["action_id"] for e in decided} >= {a.id for a in actions}
