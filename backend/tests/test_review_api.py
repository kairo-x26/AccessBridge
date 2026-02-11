from __future__ import annotations

from app.integrations import simulated_ehr as ehr
from tests.factories import make_org, make_user


def _provider(client, admin, **kw):
    body = {
        "name": "Prairie Heart Associates",
        "specialty": "cardiology",
        "network_reference": "NPI-PHA",
        **kw,
    }
    return client.post("/v1/providers", headers=admin.headers(), json=body).json()


def _import(
    client, coord, letter=None, docs=None, patient=ehr.ROSA, rid="sr-1", performer_ref="NPI-PHA"
):
    letter = letter or ehr.referral_letter(patient, specialty="Cardiology", reason="Palpitations")
    documents = (
        docs
        if docs is not None
        else [
            ("referral.txt", "text/plain", letter),
            (
                "visit-note.txt",
                "text/plain",
                b"Office visit progress note\nAssessment: palpitations\nPlan: refer",
            ),
        ]
    )
    ref = ehr.SyntheticReferral(
        rid,
        patient,
        "Cardiology",
        "Palpitations",
        performer="Prairie Heart Associates",
        performer_ref=performer_ref,
        documents=documents,
    )
    return client.post(
        "/v1/referrals/import", headers=coord.headers(), json={"bundle": ehr.bundle(ref)}
    ).json()["imported"][0]


def _setup(client):
    org = make_org()
    admin = make_user(org, "admin")
    coord = make_user(org, "coordinator")
    _provider(client, admin)
    return org, admin, coord


def test_complete_package_flow(client):
    _, _, coord = _setup(client)
    h = coord.headers()
    rid = _import(client, coord)
    a = client.post(f"/v1/referrals/{rid}/analyze/sync", headers=h).json()
    assert a["documents_processed"] == 2 and a["open_blocking"] == 0, a
    fields = client.get(f"/v1/referrals/{rid}/fields", headers=h).json()
    by = {f["name"]: f for f in fields}
    assert by["member_id"]["value"] == "MBR-55120934" and by["member_id"]["critical"]
    v = client.get(f"/v1/referrals/{rid}/validation", headers=h).json()
    assert not v["ready"] and any("member id" in b for b in v["blockers"])
    for f in fields:
        if f["critical"]:
            r = client.patch(f"/v1/fields/{f['id']}", headers=h, json={"action": "accept"})
            assert r.status_code == 200
    preview = client.get(f"/v1/referrals/{rid}/package", headers=h).json()
    assert preview["ready"], preview["blockers"]
    pkg = client.post(
        f"/v1/referrals/{rid}/package/approve",
        headers=h,
        json={"expected_version": preview["version"], "note": "Looks complete"},
    )
    assert pkg.status_code == 201, pkg.text
    d = client.get(f"/v1/referrals/{rid}", headers=h).json()
    assert d["status"] == "ready"
    assert d["events"][-1]["evidence_type"] == "package_approval"
    assert pkg.json()["id"] in d["events"][-1]["evidence_reference"]
    assert pkg.json()["contents"]["fields"]["member_id"]["value"] == "MBR-55120934"
    # Approved package locks field edits.
    locked = client.patch(f"/v1/fields/{fields[0]['id']}", headers=h, json={"action": "reject"})
    assert locked.status_code == 422


def test_missing_information_creates_issues_and_tasks_without_inventing(client):
    _, _, coord = _setup(client)
    h = coord.headers()
    letter = ehr.referral_letter(
        ehr.ROSA, specialty="Cardiology", reason="Palpitations", insurance=None, member_id=None
    )
    rid = _import(client, coord, letter=letter, docs=[("referral.txt", "text/plain", letter)])
    a = client.post(f"/v1/referrals/{rid}/analyze/sync", headers=h).json()
    assert {"field:insurance_payer", "field:member_id", "document:clinical_note"} <= set(
        a["issues"]
    )
    names = {f["name"] for f in client.get(f"/v1/referrals/{rid}/fields", headers=h).json()}
    assert "member_id" not in names and "insurance_payer" not in names
    tasks = client.get(f"/v1/tasks?referral_id={rid}", headers=h).json()["items"]
    assert sum(t["kind"] == "missing_info" for t in tasks) == 3
    # Running analysis again doesn't duplicate work.
    client.post(f"/v1/referrals/{rid}/analyze/sync", headers=h)
    again = client.get(f"/v1/tasks?referral_id={rid}", headers=h).json()["items"]
    assert len(again) == len(tasks)
    # Uploading the missing document resolves its issue and task.
    client.post(
        f"/v1/referrals/{rid}/documents",
        headers=h,
        files={
            "file": ("note.txt", b"Progress note\nAssessment: stable\nPlan: refer", "text/plain")
        },
    )
    client.post(f"/v1/referrals/{rid}/analyze/sync", headers=h)
    v = client.get(f"/v1/referrals/{rid}/validation", headers=h).json()
    st = {i["item_key"]: i["status"] for i in v["issues"]}
    assert st["document:clinical_note"] == "resolved" and st["field:member_id"] == "open"


def test_identity_mismatch_blocks_and_cannot_be_waived(client):
    _, _, coord = _setup(client)
    h = coord.headers()
    other = ehr.SyntheticPatient("100234", "Rosa", "Delgado", "1971-09-09")
    letter = ehr.referral_letter(other, specialty="Cardiology", reason="x")
    rid = _import(client, coord, letter=letter)
    client.post(f"/v1/referrals/{rid}/analyze/sync", headers=h)
    v = client.get(f"/v1/referrals/{rid}/validation", headers=h).json()
    issue = next(i for i in v["issues"] if i["item_key"] == "identity:birth_date")
    assert issue["severity"] == "blocking"
    r = client.post(
        f"/v1/validation-issues/{issue['id']}/waive", headers=h, json={"reason": "seems fine"}
    )
    assert r.status_code == 422
    tasks = client.get(f"/v1/tasks?referral_id={rid}", headers=h).json()["items"]
    assert any(t["kind"] == "exception" and t["priority"] == "high" for t in tasks)
    # Rejecting the wrong extracted value (e.g. a scanning error) clears the mismatch.
    dob = next(
        f
        for f in client.get(f"/v1/referrals/{rid}/fields", headers=h).json()
        if f["name"] == "birth_date"
    )
    client.patch(
        f"/v1/fields/{dob['id']}",
        headers=h,
        json={"action": "correct", "corrected_value": "1968-03-14"},
    )
    v = client.get(f"/v1/referrals/{rid}/validation", headers=h).json()
    assert (
        next(i for i in v["issues"] if i["item_key"] == "identity:birth_date")["status"]
        == "resolved"
    )


def test_waive_warning_and_provider_problems(client):
    org, admin, coord = _setup(client)
    h = coord.headers()
    rid = _import(client, coord, performer_ref="unknown")
    a = client.post(f"/v1/referrals/{rid}/analyze/sync", headers=h).json()
    assert "provider:destination" in a["issues"]
    v = client.get(f"/v1/referrals/{rid}/validation", headers=h).json()
    prov = next(i for i in v["issues"] if i["item_key"] == "provider:destination")
    assert (
        client.post(
            f"/v1/validation-issues/{prov['id']}/waive",
            headers=h,
            json={"reason": "will pick later"},
        ).status_code
        == 422
    )
    closed = _provider(
        client, admin, name="Closed Clinic", network_reference="NPI-CL", accepts_referrals=False
    )
    ver = client.get(f"/v1/referrals/{rid}", headers=h).json()["version"]
    r = client.patch(
        f"/v1/referrals/{rid}",
        headers=h,
        json={"expected_version": ver, "provider_id": closed["id"]},
    )
    assert r.status_code == 422


def test_conflicting_documents_flag_conflict(client):
    _, _, coord = _setup(client)
    h = coord.headers()
    l1 = ehr.referral_letter(ehr.ROSA, specialty="Cardiology", reason="x", member_id="MBR-1111")
    l2 = b"Insurance card\nMember ID: MBR-2222\nGroup #: 7"
    rid = _import(
        client, coord, letter=l1, docs=[("a.txt", "text/plain", l1), ("b.txt", "text/plain", l2)]
    )
    a = client.post(f"/v1/referrals/{rid}/analyze/sync", headers=h).json()
    assert "conflict:member_id" in a["issues"]


def test_checklist_override(client):
    _, admin, coord = _setup(client)
    items = [
        {"label": "Signed referral form", "kind": "document", "target": "referral_form"},
        {"label": "Member ID", "kind": "field", "target": "member_id"},
    ]
    r = client.put("/v1/checklists/cardiology", headers=admin.headers(), json={"items": items})
    assert r.status_code == 200 and r.json()["version"] == "v1"
    bad = client.put(
        "/v1/checklists/cardiology",
        headers=admin.headers(),
        json={"items": [{"label": "x", "kind": "field", "target": "shoe_size"}]},
    )
    assert bad.status_code == 422
    assert (
        client.put(
            "/v1/checklists/cardiology", headers=coord.headers(), json={"items": items}
        ).status_code
        == 403
    )
    rid = _import(client, coord)
    a = client.post(f"/v1/referrals/{rid}/analyze/sync", headers=coord.headers()).json()
    assert a["checklist_version"] == "v1"
    lists = client.get("/v1/checklists", headers=coord.headers()).json()
    assert next(c for c in lists if c["specialty"] == "cardiology")["customized"]
    reset = client.delete("/v1/checklists/cardiology", headers=admin.headers()).json()
    assert reset["version"] == "builtin"


def test_cross_tenant_review_access(client):
    _, _, coord = _setup(client)
    rid = _import(client, coord)
    client.post(f"/v1/referrals/{rid}/analyze/sync", headers=coord.headers())
    fid = client.get(f"/v1/referrals/{rid}/fields", headers=coord.headers()).json()[0]["id"]
    other = make_user(make_org("zz", "ZZ"), "coordinator")
    oh = other.headers()
    assert (
        client.patch(f"/v1/fields/{fid}", headers=oh, json={"action": "accept"}).status_code == 404
    )
    assert client.get(f"/v1/referrals/{rid}/fields", headers=oh).status_code == 404
    assert (
        client.post(
            f"/v1/referrals/{rid}/package/approve", headers=oh, json={"expected_version": 1}
        ).status_code
        == 404
    )
