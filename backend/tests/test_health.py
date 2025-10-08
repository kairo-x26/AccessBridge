from app.core.logging import redact


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["x-request-id"]


def test_request_id_propagates(client):
    r = client.get("/health", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_redaction_removes_identifiers():
    text = "Pt SSN 123-45-6789 phone (555) 123-4567 email a.b@x.org DOB 04/12/1980 MRN: A12345"
    out = redact(text)
    for leaked in ["123-45-6789", "555", "a.b@x.org", "04/12/1980", "A12345"]:
        assert leaked not in out
