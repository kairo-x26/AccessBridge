"""Reusable multi-step API flows for workflow tests."""

from __future__ import annotations

from app.integrations import simulated_ehr as ehr
from app.workers import queue
from tests.factories import make_org, make_user


def setup_clinic(client, endpoint: str = "sim://ok", slug: str = "riverbend"):
    org = make_org(slug, slug.title())
    admin = make_user(org, "admin")
    coord = make_user(org, "coordinator")
    prov = client.post(
        "/v1/providers",
        headers=admin.headers(),
        json={
            "name": "Prairie Heart Associates",
            "specialty": "cardiology",
            "network_reference": "NPI-PHA",
            "endpoint": endpoint,
        },
    ).json()
    return org, admin, coord, prov


def import_referral(client, coord, rid="sr-1", patient=ehr.ROSA, **letter_kw):
    letter = ehr.referral_letter(
        patient, specialty="Cardiology", reason="Palpitations", **letter_kw
    )
    ref = ehr.SyntheticReferral(
        rid,
        patient,
        "Cardiology",
        "Palpitations",
        performer="Prairie Heart Associates",
        performer_ref="NPI-PHA",
        documents=[
            ("referral.txt", "text/plain", letter),
            ("note.txt", "text/plain", b"Office visit progress note\nAssessment: x"),
        ],
    )
    return client.post(
        "/v1/referrals/import", headers=coord.headers(), json={"bundle": ehr.bundle(ref)}
    ).json()["imported"][0]


def analyze_and_drain(client, coord, rid):
    r = client.post(f"/v1/referrals/{rid}/analyze", headers=coord.headers())
    assert r.status_code == 202, r.text
    queue.run_pending()
    return client.get(f"/v1/agent-runs/{r.json()['run_id']}", headers=coord.headers()).json()


def approve_package(client, coord, rid):
    h = coord.headers()
    for f in client.get(f"/v1/referrals/{rid}/fields", headers=h).json():
        if f["critical"] and f["status"] == "candidate":
            client.patch(f"/v1/fields/{f['id']}", headers=h, json={"action": "accept"})
    v = client.get(f"/v1/referrals/{rid}", headers=h).json()["version"]
    r = client.post(f"/v1/referrals/{rid}/package/approve", headers=h, json={"expected_version": v})
    assert r.status_code == 201, r.text
    return r.json()


def ready_referral(client, endpoint="sim://ok"):
    org, admin, coord, prov = setup_clinic(client, endpoint)
    rid = import_referral(client, coord)
    analyze_and_drain(client, coord, rid)
    pkg = approve_package(client, coord, rid)
    queue.run_pending()  # intake run proposes transmission
    return org, admin, coord, prov, rid, pkg
