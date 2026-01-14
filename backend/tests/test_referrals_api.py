from __future__ import annotations

from app.integrations import simulated_ehr as ehr
from tests.factories import advance, make_org, make_user


def _bundle(*refs):
    return {"bundle": ehr.bundle(*refs)}


def _rosa(rid="sr-1", **kw):
    letter = ehr.referral_letter(ehr.ROSA, specialty="Cardiology", reason="Palpitations")
    return ehr.SyntheticReferral(
        rid,
        ehr.ROSA,
        "Cardiology consult",
        "Palpitations",
        documents=[("referral.txt", "text/plain", letter)],
        **kw,
    )


def test_fhir_import_creates_traceable_record(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    r = client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa()))
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["imported"]) == 1 and not body["errors"]
    rid = body["imported"][0]
    d = client.get(f"/v1/referrals/{rid}", headers=coord.headers()).json()
    assert d["status"] == "needs_review"
    assert d["specialty"] == "cardiology"
    assert d["patient"]["display_name"] == "Rosa Delgado"
    assert d["patient"]["preferred_language"] == "es"
    assert [e["new_status"] for e in d["events"]] == ["imported", "needs_review"]
    assert d["events"][0]["evidence_reference"] == "fhir:sr-1"
    assert len(d["documents"]) == 1
    assert {o["status"] for o in d["next_statuses"]} == {"ready", "exception"}


def test_duplicate_import_creates_no_new_work(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    first = client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa()))
    again = client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa()))
    assert again.json()["duplicates"] == first.json()["imported"]
    assert client.get("/v1/referrals", headers=coord.headers()).json()["total"] == 1
    tasks = client.get("/v1/tasks", headers=coord.headers()).json()["items"]
    assert not [t for t in tasks if t["kind"] == "reconciliation"]


def test_changed_resend_creates_reconciliation_task_once(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa()))
    changed = _rosa(priority="urgent")
    for _ in range(2):
        client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(changed))
    tasks = client.get("/v1/tasks", headers=coord.headers()).json()["items"]
    assert len([t for t in tasks if t["kind"] == "reconciliation"]) == 1


def test_idempotency_key_replay_and_misuse(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    h = {**coord.headers(), "Idempotency-Key": "k-1"}
    a = client.post("/v1/referrals/import", headers=h, json=_bundle(_rosa()))
    b = client.post("/v1/referrals/import", headers=h, json=_bundle(_rosa()))
    assert a.json() == b.json() and b.headers.get("idempotent-replay") == "true"
    c = client.post("/v1/referrals/import", headers=h, json=_bundle(_rosa("sr-other")))
    assert c.status_code == 409


def test_identity_conflict_goes_to_exception(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa()))
    imposter = ehr.SyntheticPatient("100234", "Rosa", "Delgado-Smith", "1971-01-01")
    second = ehr.SyntheticReferral("sr-2", imposter, "Dermatology", "Rash")
    res = client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(second)).json()
    assert res["exceptions"] == res["imported"]
    d = client.get(f"/v1/referrals/{res['imported'][0]}", headers=coord.headers()).json()
    assert d["status"] == "exception"
    assert "identity" in d["exception_reason"]
    assert any(t["kind"] == "exception" and t["status"] == "open" for t in d["tasks"])


def test_bundle_errors_reported_per_request(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    b = ehr.bundle(_rosa())
    b["entry"].append(
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": "bad",
                "subject": {"reference": "Patient/nope"},
            }
        }
    )
    res = client.post("/v1/referrals/import", headers=coord.headers(), json={"bundle": b}).json()
    assert len(res["imported"]) == 1
    assert res["errors"][0]["source_id"] == "bad"
    bad = client.post(
        "/v1/referrals/import",
        headers=coord.headers(),
        json={"bundle": {"resourceType": "Patient"}},
    )
    assert bad.status_code == 422


def test_csv_import(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    csv_text = (
        "source_id,ehr_patient_id,given_name,family_name,birth_date,specialty,priority\n"
        "c-1,200001,Ana,Ruiz,1980-02-02,Dermatology,routine\n"
        "c-2,200002,Ben,Cho,02/03/1980,Neurology,routine\n"
        "c-3,,Cy,Doe,1980-02-02,Neurology,routine\n"
    )
    r = client.post(
        "/v1/referrals/import/csv",
        headers=coord.headers(),
        files={"file": ("refs.csv", csv_text, "text/csv")},
    )
    body = r.json()
    assert len(body["imported"]) == 1
    assert {e["row"] for e in body["errors"]} == {"3", "4"}


def test_manual_intake_and_validation(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    payload = {
        "ehr_patient_id": "300001",
        "given_name": "Lee",
        "family_name": "Park",
        "specialty": "neurology",
    }
    r = client.post("/v1/referrals", headers=coord.headers(), json=payload)
    assert r.status_code == 201 and r.json()["source_system"] == "manual"
    bad = client.post(
        "/v1/referrals", headers=coord.headers(), json={**payload, "specialty": "astrology"}
    )
    assert bad.status_code == 422


def test_list_filters_search_and_pagination(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    refs = [
        _rosa("sr-1"),
        ehr.SyntheticReferral("sr-2", ehr.JAMES, "Orthopedics", "Knee pain"),
        ehr.SyntheticReferral("sr-3", ehr.MEI, "Dermatology", "Rash"),
    ]
    client.post("/v1/referrals/import", headers=coord.headers(), json=_bundle(*refs))
    h = coord.headers()
    assert client.get("/v1/referrals?q=whitf", headers=h).json()["total"] == 1
    assert client.get("/v1/referrals?specialty=dermatology", headers=h).json()["total"] == 1
    page = client.get("/v1/referrals?page_size=2&page=2", headers=h).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert client.get("/v1/referrals?status=bogus", headers=h).status_code == 422
    assert (
        client.get("/v1/referrals?status=needs_review&status=exception", headers=h).json()["total"]
        == 3
    )


def test_clinician_sees_status_but_not_contact_details(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    doc = make_user(org, "clinician")
    rid = client.post(
        "/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa())
    ).json()["imported"][0]
    d = client.get(f"/v1/referrals/{rid}", headers=doc.headers()).json()
    assert d["status"] == "needs_review"
    assert d["patient"]["phone"] is None and d["patient"]["birth_date"] is None
    assert d["tasks"] == [] and d["next_statuses"] == []
    full = client.get(f"/v1/referrals/{rid}", headers=coord.headers()).json()
    assert full["patient"]["phone"] == "+1 555 010 2231"
    assert (
        client.post(
            f"/v1/referrals/{rid}/status-events",
            headers=doc.headers(),
            json={"to_status": "exception", "reason": "x"},
        ).status_code
        == 403
    )


def test_status_events_enforce_evidence_and_versions(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    rid = client.post(
        "/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa())
    ).json()["imported"][0]
    h = coord.headers()
    ready = client.post(
        f"/v1/referrals/{rid}/status-events", headers=h, json={"to_status": "ready"}
    )
    assert ready.status_code == 422  # must go through package approval
    advance(rid, "ready", "submitted", "acknowledged", "scheduled")
    bad = client.post(
        f"/v1/referrals/{rid}/status-events",
        headers=h,
        json={
            "to_status": "completed",
            "evidence_type": "message_delivery",
            "evidence_reference": "msg-1",
        },
    )
    assert (
        bad.status_code == 409 and bad.json()["error"]["details"]["code"] == "evidence_not_accepted"
    )
    version = client.get(f"/v1/referrals/{rid}", headers=h).json()["version"]
    stale = client.post(
        f"/v1/referrals/{rid}/status-events",
        headers=h,
        json={
            "to_status": "completed",
            "evidence_type": "consult_note",
            "evidence_reference": "doc-9",
            "expected_version": version - 1,
        },
    )
    assert stale.status_code == 409
    ok = client.post(
        f"/v1/referrals/{rid}/status-events",
        headers=h,
        json={
            "to_status": "completed",
            "evidence_type": "consult_note",
            "evidence_reference": "doc-9",
            "expected_version": version,
        },
    )
    assert ok.status_code == 201
    reopen = client.post(
        f"/v1/referrals/{rid}/status-events",
        headers=h,
        json={"to_status": "exception", "reason": "wrong patient", "correction": True},
    )
    assert reopen.status_code == 403
    admin = make_user(org, "admin")
    reopen = client.post(
        f"/v1/referrals/{rid}/status-events",
        headers=admin.headers(),
        json={"to_status": "exception", "reason": "wrong patient", "correction": True},
    )
    assert reopen.status_code == 201 and reopen.json()["correction"] is True


def test_rejected_transition_is_audited(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    sec = make_user(org, "security")
    rid = client.post(
        "/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa())
    ).json()["imported"][0]
    client.post(
        f"/v1/referrals/{rid}/status-events",
        headers=coord.headers(),
        json={"to_status": "completed", "evidence_type": "consult_note", "evidence_reference": "x"},
    )
    events = client.get(
        f"/v1/audit-events?resource_ref={rid}&operation=referral.transition", headers=sec.headers()
    ).json()["items"]
    assert any(e["outcome"] == "rejected" for e in events)


def test_cross_tenant_referral_access_rejected(client):
    a, b = make_org("a", "A"), make_org("b", "B")
    ca, cb = make_user(a, "coordinator"), make_user(b, "coordinator")
    rid = client.post("/v1/referrals/import", headers=ca.headers(), json=_bundle(_rosa())).json()[
        "imported"
    ][0]
    h = cb.headers()
    assert client.get(f"/v1/referrals/{rid}", headers=h).status_code == 404
    assert client.get(f"/v1/referrals/{rid}/events", headers=h).status_code == 404
    assert (
        client.post(
            f"/v1/referrals/{rid}/status-events",
            headers=h,
            json={"to_status": "exception", "reason": "x"},
        ).status_code
        == 404
    )
    assert (
        client.patch(f"/v1/referrals/{rid}", headers=h, json={"expected_version": 1}).status_code
        == 404
    )
    assert client.get("/v1/referrals", headers=h).json()["total"] == 0
    doc_id = client.get(f"/v1/referrals/{rid}", headers=ca.headers()).json()["documents"][0]["id"]
    assert client.get(f"/v1/documents/{doc_id}/content", headers=h).status_code == 404
    # Same source id in another tenant is a separate referral, not a duplicate.
    rb = client.post("/v1/referrals/import", headers=h, json=_bundle(_rosa())).json()
    assert rb["imported"] and rb["imported"] != [rid]


def test_document_upload_and_audited_read(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    sec = make_user(org, "security")
    rid = client.post(
        "/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa())
    ).json()["imported"][0]
    up = client.post(
        f"/v1/referrals/{rid}/documents",
        headers=coord.headers(),
        files={"file": ("insurance.txt", b"Member ID: X1", "text/plain")},
    )
    assert up.status_code == 201
    exe = client.post(
        f"/v1/referrals/{rid}/documents",
        headers=coord.headers(),
        files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
    )
    assert exe.status_code == 422
    content = client.get(f"/v1/documents/{up.json()['id']}/content", headers=coord.headers())
    assert content.content == b"Member ID: X1"
    assert content.headers["cache-control"] == "no-store"
    reads = client.get("/v1/audit-events?operation=document.read", headers=sec.headers()).json()[
        "items"
    ]
    assert reads and reads[0]["actor"] == f"user:{coord.user_id}"


def test_assign_owner_with_version_check(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    rid = client.post(
        "/v1/referrals/import", headers=coord.headers(), json=_bundle(_rosa())
    ).json()["imported"][0]
    v = client.get(f"/v1/referrals/{rid}", headers=coord.headers()).json()["version"]
    ok = client.patch(
        f"/v1/referrals/{rid}",
        headers=coord.headers(),
        json={"expected_version": v, "owner_id": coord.user_id},
    )
    assert ok.status_code == 200 and ok.json()["owner_name"] == "Test coordinator"
    again = client.patch(
        f"/v1/referrals/{rid}",
        headers=coord.headers(),
        json={"expected_version": v, "clear_owner": True},
    )
    assert again.status_code == 409
    mine = client.get("/v1/referrals?owner_id=me", headers=coord.headers()).json()
    assert mine["total"] == 1
