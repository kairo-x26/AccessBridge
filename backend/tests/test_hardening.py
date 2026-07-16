from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.core import db
from app.core.config import get_settings
from app.core.db import utcnow
from app.models import ExtractedField, Referral, ReferralDocument, ReferralStatusEvent
from app.services import retention
from tests import flows
from tests.factories import PASSWORD, make_org, make_user


def test_security_headers_on_every_response(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_oversized_requests_rejected(client):
    r = client.post(
        "/v1/auth/login",
        content=b"{}",
        headers={"content-length": str(13 * 1024 * 1024), "content-type": "application/json"},
    )
    assert r.status_code == 413


def test_metrics_need_token_when_configured(client, monkeypatch):
    client.get("/health")
    ok = client.get("/metrics")
    assert ok.status_code == 200 and "accessbridge_http_requests_total" in ok.text
    assert 'route="/health"' in ok.text
    monkeypatch.setattr(get_settings(), "metrics_token", "scrape-secret")
    assert client.get("/metrics").status_code == 401
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"}).status_code == 200
    )


def test_login_is_rate_limited_per_account(client):
    org = make_org()
    u = make_user(org, "coordinator")
    codes = [
        client.post(
            "/v1/auth/login",
            json={"organization": "riverbend", "email": u.email, "password": "Wrong-password-1"},
        ).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    r = client.post(
        "/v1/auth/login", json={"organization": "riverbend", "email": u.email, "password": PASSWORD}
    )
    assert r.status_code == 429
    assert r.json()["error"]["details"]["retry_after_seconds"] > 0


def _completed_referral(client):
    org, admin, coord, prov, rid = flows.acknowledged_referral(client)
    flows.adopt_templates(client, org, admin)
    flows.consent(client, coord, rid)
    client.post(
        f"/v1/referrals/{rid}/communications",
        headers=coord.headers(),
        json={"template_key": "schedule_prompt"},
    )
    from tests.factories import advance

    advance(rid, "scheduled", "completed")
    with db.session_factory()() as s:
        s.get(Referral, rid).status_changed_at = utcnow() - timedelta(days=3000)
        s.commit()
    return admin, coord, rid


def test_retention_purges_working_data_but_keeps_history(client):
    admin, coord, rid = _completed_referral(client)
    with db.session_factory()() as s:
        files = [
            Path(get_settings().storage_dir) / d.storage_uri.removeprefix("local://")
            for d in s.query(ReferralDocument).filter_by(referral_id=rid)
        ]
        events_before = s.query(ReferralStatusEvent).filter_by(referral_id=rid).count()
        assert (
            all(f.exists() for f in files)
            and s.query(ExtractedField).filter_by(referral_id=rid).count() > 0
        )
        assert retention.sweep(s) == 1
        s.commit()
        assert not any(f.exists() for f in files)
        assert s.query(ExtractedField).filter_by(referral_id=rid).count() == 0
        assert s.query(ReferralStatusEvent).filter_by(referral_id=rid).count() == events_before
        assert retention.sweep(s) == 0  # idempotent
    d = client.get(f"/v1/referrals/{rid}", headers=coord.headers()).json()
    assert d["status"] == "completed" and d["purged_at"]
    assert d["patient"]["phone"] is None
    msgs = client.get(f"/v1/referrals/{rid}/communications", headers=coord.headers()).json()
    assert msgs and all(m["body"] is None for m in msgs)


def test_legal_hold_blocks_retention(client):
    admin, coord, rid = _completed_referral(client)
    assert (
        client.post(
            f"/v1/referrals/{rid}/legal-hold",
            headers=coord.headers(),
            json={"hold": True, "reason": "Records request"},
        ).status_code
        == 403
    )
    r = client.post(
        f"/v1/referrals/{rid}/legal-hold",
        headers=admin.headers(),
        json={"hold": True, "reason": "Records request"},
    )
    assert r.status_code == 200 and r.json()["legal_hold"] is True
    with db.session_factory()() as s:
        assert retention.sweep(s) == 0


def test_recent_and_open_referrals_are_kept(client):
    org, admin, coord, prov, rid = flows.submitted_referral(client)
    with db.session_factory()() as s:
        s.get(Referral, rid).status_changed_at = utcnow() - timedelta(days=4000)
        s.commit()
        assert retention.sweep(s) == 0
    _ = make_user  # keep import used
