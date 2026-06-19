from __future__ import annotations

from tests import flows
from tests.factories import make_user


def test_metrics_reflect_workflow(client):
    org, admin, coord, prov, rid = flows.submitted_referral(client)
    flows.import_referral(client, coord, rid="sr-2")
    r = client.get("/v1/reports/referrals", headers=admin.headers())
    assert r.status_code == 200
    m = r.json()
    assert m["totals"]["referrals"] == 2 and m["totals"]["open"] == 2
    assert m["status_distribution"]["submitted"] == 1
    assert m["status_distribution"]["needs_review"] == 1
    assert m["totals"]["median_days_to_submitted"] is not None
    assert m["age_buckets"][0]["count"] == 2
    assert m["agent"]["approved"] == 1 and m["agent"]["acceptance_rate"] == 1.0
    assert "completed_care_rate" in m["definitions"]
    assert m["by_specialty"][0]["specialty"] == "cardiology"
    only = client.get("/v1/reports/referrals?specialty=neurology", headers=admin.headers())
    assert only.json()["totals"]["referrals"] == 0


def test_metrics_permissions_and_isolation(client):
    org, admin, coord, prov, rid = flows.submitted_referral(client)
    nav = make_user(org, "navigator")
    assert client.get("/v1/reports/referrals", headers=nav.headers()).status_code == 403
    _, other_admin, _, _ = flows.setup_clinic(client, slug="lakeside")
    m = client.get("/v1/reports/referrals", headers=other_admin.headers()).json()
    assert m["totals"]["referrals"] == 0 and m["agent"]["proposals"] == 0


def test_since_days_filters_by_import_date(client):
    from datetime import timedelta

    from app.core import db
    from app.core.db import utcnow
    from app.models import Referral

    org, admin, coord, prov = flows.setup_clinic(client)
    rid = flows.import_referral(client, coord)
    flows.import_referral(client, coord, rid="sr-2")
    with db.session_factory()() as s:
        s.get(Referral, rid).created_at = utcnow() - timedelta(days=45)
        s.commit()
    m = client.get("/v1/reports/referrals?since_days=30", headers=admin.headers()).json()
    assert m["totals"]["referrals"] == 1
    assert (
        client.get("/v1/reports/referrals?since_days=0", headers=admin.headers()).status_code == 422
    )
