"""Seed a synthetic clinic network for development and the demo.

Drives the real API in-process (so every record goes through the same rules, approvals and
audit as production traffic), then back-dates timestamps to give referrals realistic ages.
All people and identifiers are fictional.

Run: ``uv run python -m app.seed [--reset]``
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import db
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.security import create_access_token
from app.domain.templates import BUILTIN
from app.integrations import simulated_ehr as ehr
from app.models import (
    AgentRun,
    AuditEvent,
    Communication,
    Organization,
    Referral,
    ReferralStatusEvent,
    Task,
    User,
)
from app.services import auth

PASSWORD = "Demo-Password-2026"  # noqa: S105 - synthetic demo accounts only
ORG_SLUG = "riverbend"

STAFF = [
    ("admin", "Dana Whitaker", "dana.admin@riverbend.example.org"),
    ("admin", "Marcus Lee", "marcus.admin@riverbend.example.org"),
    ("coordinator", "Priya Raman", "priya.coordinator@riverbend.example.org"),
    ("coordinator", "Tomás Herrera", "tomas.coordinator@riverbend.example.org"),
    ("navigator", "Grace Mensah", "grace.navigator@riverbend.example.org"),
    ("clinician", "Dr. Amara Okafor", "amara.clinician@riverbend.example.org"),
    ("security", "Ivy Chen", "ivy.security@riverbend.example.org"),
]

PROVIDERS = [
    ("Prairie Heart Associates", "cardiology", "NPI-PHA", "+1 555 020 1100", "sim://ok"),
    ("Lakeside Dermatology", "dermatology", "NPI-LSD", "+1 555 020 2200", "sim://ok"),
    ("Riverbend Endocrine Clinic", "endocrinology", "NPI-REC", "+1 555 020 3300", "sim://ok"),
    ("Northgate GI Partners", "gastroenterology", "NPI-NGI", "+1 555 020 4400", "sim://flaky"),
    ("Cedar Neurology Group", "neurology", "NPI-CNG", "+1 555 020 5500", "sim://ok"),
    ("Summit Orthopedics", "orthopedics", "NPI-SUM", "+1 555 020 6600", "sim://ok"),
    ("Clearview Eye Center", "ophthalmology", "NPI-CEC", "+1 555 020 7700", "sim://ok"),
    ("Harbor Behavioral Health", "behavioral_health", "NPI-HBH", "+1 555 020 8800", "sim://down"),
]

PATIENTS = [
    ehr.SyntheticPatient(
        "100234", "Rosa", "Delgado", "1968-03-14", "+1 555 010 2231", language="es"
    ),
    ehr.SyntheticPatient("100871", "James", "Whitfield", "1955-11-02", "+1 555 010 7781"),
    ehr.SyntheticPatient("101552", "Mei", "Tanaka", "1990-07-21", "+1 555 010 4410"),
    ehr.SyntheticPatient("102118", "Amina", "Hassan", "1982-01-30", "+1 555 010 3392"),
    ehr.SyntheticPatient(
        "102774", "Luis", "Moreno", "1974-09-12", "+1 555 010 6620", language="es"
    ),
    ehr.SyntheticPatient("103305", "Grace", "Okafor", "1961-05-05", "+1 555 010 1187"),
    ehr.SyntheticPatient("103890", "Tomas", "Novak", "1949-12-19", "+1 555 010 9043"),
    ehr.SyntheticPatient("104412", "Priya", "Nair", "1995-02-08", "+1 555 010 5576"),
    ehr.SyntheticPatient("104967", "Samuel", "Brooks", "1970-08-27", "+1 555 010 8124"),
    ehr.SyntheticPatient("105530", "Ivy", "Romero", "1987-04-16", "+1 555 010 2468", language="es"),
    ehr.SyntheticPatient("106081", "Daniel", "Kim", "1958-10-03", "+1 555 010 1357"),
    ehr.SyntheticPatient("106642", "Fatima", "Yusuf", "1979-06-24", "+1 555 010 9753"),
    ehr.SyntheticPatient("107203", "Noah", "Petrov", "2001-03-11", "+1 555 010 8642"),
    ehr.SyntheticPatient(
        "107764", "Elena", "Alvarez", "1966-11-29", "+1 555 010 7531", language="es"
    ),
    ehr.SyntheticPatient("108325", "Kwame", "Mensah", "1952-07-07", "+1 555 010 6420"),
    ehr.SyntheticPatient(
        "108886", "Lucia", "Romero", "1993-09-18", "+1 555 010 3197", language="es"
    ),
]

REASONS = {
    "cardiology": ("Cardiology consult", "Evaluate palpitations and elevated blood pressure"),
    "dermatology": ("Dermatology", "Changing mole on left forearm"),
    "endocrinology": ("Endocrinology", "Type 2 diabetes management"),
    "gastroenterology": ("Gastroenterology", "Chronic abdominal pain"),
    "neurology": ("Neurology", "Recurrent migraines"),
    "orthopedics": ("Orthopedics", "Chronic knee pain after physical therapy"),
    "ophthalmology": ("Ophthalmology", "Diabetic eye exam"),
    "behavioral_health": ("Behavioral health", "Anxiety, medication management"),
}
EXTRA_DOCS = {
    "cardiology": (
        "visit-note.txt",
        b"Office visit progress note\nAssessment: palpitations\nPlan: refer to cardiology",
    ),
    "endocrinology": (
        "labs.txt",
        b"Laboratory results\nSpecimen: blood\nHemoglobin A1c 9.1%\nReference range 4.0-5.6",
    ),
    "gastroenterology": (
        "visit-note.txt",
        b"Progress note\nAssessment: abdominal pain\nPlan: GI referral",
    ),
    "neurology": ("visit-note.txt", b"Office visit note\nAssessment: migraines\nPlan: refer"),
    "orthopedics": (
        "xray.txt",
        b"Radiology report\nX-ray left knee\nFindings: narrowing\nImpression: osteoarthritis",
    ),
    "behavioral_health": (
        "consent.txt",
        b"Consent to share records\nI authorize release of "
        b"information to the specialist.\nSignature: on file",
    ),
}


@dataclass
class Ctx:
    client: TestClient
    org_id: str
    users: dict[str, Any]
    providers: dict[str, dict[str, Any]]

    def h(self, email: str) -> dict[str, str]:
        u = self.users[email]
        token = create_access_token(
            user_id=u.id, organization_id=u.organization_id, role=u.role, mfa=True
        )
        return {"Authorization": f"Bearer {token}"}


def _drain() -> None:
    from app.workers import queue

    queue.run_pending(limit=500)


def _org_and_staff() -> tuple[str, dict[str, User]]:
    with db.session_factory()() as s:
        org = Organization(
            name="Riverbend Community Health",
            slug=ORG_SLUG,
            configuration={"preauthorized_tools": [], "preauthorized_templates": []},
        )
        s.add(org)
        s.flush()
        users = {}
        for role, name, email in STAFF:
            users[email] = auth.create_user(
                s, organization_id=org.id, email=email, full_name=name, role=role, password=PASSWORD
            )
        s.commit()
        for u in users.values():
            s.refresh(u)
        return org.id, users


def _import(
    ctx: Ctx,
    i: int,
    patient: ehr.SyntheticPatient,
    specialty: str,
    *,
    missing_member: bool = False,
    priority: str = "routine",
) -> str:
    coord = "priya.coordinator@riverbend.example.org"
    code_text, reason = REASONS[specialty]
    name, *_ = next(p for p in PROVIDERS if p[1] == specialty)
    letter = ehr.referral_letter(
        patient,
        specialty=code_text,
        reason=reason,
        member_id=None if missing_member else f"MBR-{55120934 + i}",
    )
    docs = [("referral-letter.txt", "text/plain", letter)]
    if specialty in EXTRA_DOCS:
        fn, data = EXTRA_DOCS[specialty]
        docs.append((fn, "text/plain", data))
    ref = ehr.SyntheticReferral(
        f"SR-2026-{1040 + i}",
        patient,
        code_text,
        reason,
        priority=priority,
        performer=name,
        performer_ref=next(p[2] for p in PROVIDERS if p[1] == specialty),
        documents=docs,
    )
    r = ctx.client.post(
        "/v1/referrals/import", headers=ctx.h(coord), json={"bundle": ehr.bundle(ref)}
    )
    r.raise_for_status()
    return r.json()["imported"][0]


def _analyze(ctx: Ctx, rid: str) -> None:
    ctx.client.post(
        f"/v1/referrals/{rid}/analyze", headers=ctx.h("priya.coordinator@riverbend.example.org")
    ).raise_for_status()
    _drain()


def _approve_package(ctx: Ctx, rid: str, who: str) -> None:
    h = ctx.h(who)
    for f in ctx.client.get(f"/v1/referrals/{rid}/fields", headers=h).json():
        if f["critical"] and f["status"] == "candidate":
            ctx.client.patch(f"/v1/fields/{f['id']}", headers=h, json={"action": "accept"})
    v = ctx.client.get(f"/v1/referrals/{rid}", headers=h).json()["version"]
    ctx.client.post(
        f"/v1/referrals/{rid}/package/approve", headers=h, json={"expected_version": v}
    ).raise_for_status()
    _drain()


def _approve_pending(ctx: Ctx, rid: str, who: str, tool: str) -> None:
    h = ctx.h(who)
    for a in ctx.client.get("/v1/approvals", headers=h).json():
        if a["referral_id"] == rid and a["action"]["tool"] == tool:
            ctx.client.post(
                f"/v1/approvals/{a['id']}/decision", headers=h, json={"decision": "approved"}
            ).raise_for_status()
    _drain()


def _assign(ctx: Ctx, rid: str, email: str) -> None:
    h = ctx.h("priya.coordinator@riverbend.example.org")
    v = ctx.client.get(f"/v1/referrals/{rid}", headers=h).json()["version"]
    ctx.client.patch(
        f"/v1/referrals/{rid}",
        headers=h,
        json={"expected_version": v, "owner_id": ctx.users[email].id},
    )


def _fhir(ctx: Ctx, source_id: str, status: str, version: int, **kw: Any) -> None:
    ctx.client.post(
        "/v1/integrations/fhir/task-updates",
        headers=ctx.h("priya.coordinator@riverbend.example.org"),
        json={"resources": [ehr.task_update(source_id, status, version=version, **kw)]},
    ).raise_for_status()
    _drain()


def _backdate(rid: str, days: int) -> None:
    """Shift a referral's whole history back so ages and durations look real."""
    delta = timedelta(days=days)
    with db.session_factory()() as s:
        r = s.get(Referral, rid)
        assert r is not None
        r.created_at -= delta
        r.status_changed_at -= delta
        events = s.scalars(
            select(ReferralStatusEvent)
            .where(ReferralStatusEvent.referral_id == rid)
            .order_by(ReferralStatusEvent.timestamp)
        ).all()
        n = max(1, len(events) - 1)
        for i, e in enumerate(events):
            e.timestamp -= delta - timedelta(days=days * i / n * 0.85)
        for t in s.scalars(select(Task).where(Task.referral_id == rid)):
            t.created_at -= delta / 2
            if t.due_at:
                t.due_at -= delta / 3
        for run in s.scalars(select(AgentRun).where(AgentRun.referral_id == rid)):
            run.created_at -= delta / 2
        s.commit()


def seed(reset: bool = False) -> dict[str, Any]:
    from app.main import create_app

    if reset:
        db.Base.metadata.drop_all(db.engine())
    db.Base.metadata.create_all(db.engine())
    with db.session_factory()() as s:
        if s.scalar(select(Organization).where(Organization.slug == ORG_SLUG)):
            return {"status": "exists", "organization": ORG_SLUG}
    rng = random.Random(2026)  # noqa: S311 - synthetic data
    org_id, users = _org_and_staff()
    client = TestClient(create_app())
    ctx = Ctx(client, org_id, users, {})
    admin, admin2 = "dana.admin@riverbend.example.org", "marcus.admin@riverbend.example.org"
    coord, coord2 = (
        "priya.coordinator@riverbend.example.org",
        "tomas.coordinator@riverbend.example.org",
    )
    nav = "grace.navigator@riverbend.example.org"

    for name, spec, ref, phone, endpoint in PROVIDERS:
        p = client.post(
            "/v1/providers",
            headers=ctx.h(admin),
            json={
                "name": name,
                "specialty": spec,
                "network_reference": ref,
                "phone": phone,
                "endpoint": endpoint,
                "location": "Riverbend, IL",
                "contact_method": "direct",
                "languages": ["en", "es"] if spec in ("cardiology", "endocrinology") else ["en"],
            },
        )
        p.raise_for_status()
        ctx.providers[spec] = p.json()
    for (key, lang), body in BUILTIN.items():
        t = client.put(
            f"/v1/templates/{key}/{lang}", headers=ctx.h(admin), json={"body": body}
        ).json()
        client.post(f"/v1/templates/{t['id']}/review", headers=ctx.h(admin2))

    plan = [
        # (patient index, specialty, target stage, age days, owner)
        (0, "cardiology", "completed", 41, coord),
        (1, "orthopedics", "scheduled_past", 33, coord),
        (2, "dermatology", "acknowledged", 19, coord2),
        (3, "endocrinology", "submitted_stale", 16, coord),
        (4, "cardiology", "awaiting_transmit", 6, coord),
        (5, "neurology", "needs_review", 3, None),
        (6, "gastroenterology", "missing_info", 9, coord2),
        (7, "ophthalmology", "needs_review", 1, None),
        (8, "behavioral_health", "transmit_failed", 12, coord),
        (9, "endocrinology", "patient_replied", 22, nav),
        (10, "orthopedics", "identity_exception", 4, coord2),
        (11, "dermatology", "submitted", 8, coord2),
        (12, "neurology", "declined", 27, coord),
        (13, "cardiology", "scheduled", 14, coord),
        (14, "ophthalmology", "ready_review", 2, coord),
        (15, "gastroenterology", "needs_review", 0, None),
    ]
    created: dict[str, str] = {}
    for i, (pi, spec, stage, age, owner) in enumerate(plan):
        patient = PATIENTS[pi]
        if stage == "identity_exception":
            patient = ehr.SyntheticPatient(
                PATIENTS[0].mrn,
                "Rosa",
                "Delgado-Ruiz",
                "1972-02-02",
                "+1 555 010 2231",
                language="es",
            )
        rid = _import(
            ctx,
            i,
            patient,
            spec,
            missing_member=stage == "missing_info",
            priority="urgent" if stage == "awaiting_transmit" else "routine",
        )
        created[stage + f"-{i}"] = rid
        if owner:
            _assign(ctx, rid, owner)
        if stage in ("identity_exception",):
            _backdate(rid, age)
            continue
        _analyze(ctx, rid)
        if stage in ("needs_review", "missing_info"):
            _backdate(rid, age)
            continue
        if stage == "ready_review":
            _backdate(rid, age)
            continue
        _approve_package(ctx, rid, coord)
        if stage == "awaiting_transmit":
            _backdate(rid, age)
            continue
        _approve_pending(ctx, rid, coord, "transmit_referral_package")
        source = f"SR-2026-{1040 + i}"
        if stage == "transmit_failed":
            from app.workers import queue

            for k in range(8):
                queue.run_pending(now=utcnow() + timedelta(hours=2 * (k + 1)))
            _backdate(rid, age)
            continue
        if stage in ("submitted", "submitted_stale"):
            _backdate(rid, age)
            continue
        _fhir(ctx, source, "accepted", 1)
        if stage == "declined":
            _fhir(ctx, source, "rejected", 2, note="Patient declined when the office called.")
            _backdate(rid, age)
            continue
        if stage in ("acknowledged", "patient_replied"):
            if stage == "patient_replied":
                h = ctx.h(nav)
                pid = client.get(f"/v1/referrals/{rid}", headers=h).json()["patient"]["id"]
                client.patch(
                    f"/v1/patients/{pid}/contact",
                    headers=h,
                    json={"consent_reference": "sms-consent-2026", "contact_verified": True},
                )
                client.post(
                    f"/v1/referrals/{rid}/communications",
                    headers=h,
                    json={"template_key": "schedule_prompt"},
                ).raise_for_status()
                client.post(
                    "/v1/dev/simulate/patient-reply",
                    headers=h,
                    json={"phone": patient.phone, "body": "2 necesito ayuda con transporte"},
                )
            _backdate(rid, age)
            continue
        appt = (
            utcnow() + timedelta(days=rng.randint(3, 12))
            if stage == "scheduled"
            else utcnow() - timedelta(days=4)
        )
        _fhir(ctx, source, "in-progress", 2, appointment=appt.isoformat())
        if stage == "completed":
            note = (
                f"{ctx.providers[spec]['name']} — Consultation Note\nPatient Name: "
                f"{patient.given} {patient.family}\nDOB: {patient.birth_date}\nThank you "
                "for this referral. Seen in clinic.\nRecommendations: follow up with "
                "primary care."
            ).encode()
            client.post(
                f"/v1/referrals/{rid}/documents",
                headers=ctx.h(coord),
                files={"file": ("consult-note.txt", note, "text/plain")},
            )
            _drain()
            _approve_pending(ctx, rid, coord, "propose_completion")
        _backdate(rid, age)

    # Back-date the follow-up clock for stale submissions and run the sweeps once.
    with db.session_factory()() as s:
        for key, rid in created.items():
            if key.startswith(("submitted_stale", "scheduled_past")):
                r = s.get(Referral, rid)
                assert r is not None
                r.status_changed_at = utcnow() - timedelta(days=9)
        s.commit()
    from app.workers.run import schedule_sweeps

    schedule_sweeps()
    _drain()
    with db.session_factory()() as s:
        counts = {
            "referrals": len(s.scalars(select(Referral.id)).all()),
            "tasks": len(s.scalars(select(Task.id)).all()),
            "messages": len(s.scalars(select(Communication.id)).all()),
            "audit_events": len(s.scalars(select(AuditEvent.id)).all()),
        }
    return {
        "status": "seeded",
        "organization": ORG_SLUG,
        "password": PASSWORD,
        "users": [e for _, _, e in STAFF],
        **counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    args = parser.parse_args()
    if get_settings().environment == "production":
        raise SystemExit("Refusing to seed synthetic data in production.")
    import json

    print(json.dumps(seed(args.reset), indent=2))


if __name__ == "__main__":
    main()
