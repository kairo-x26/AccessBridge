from __future__ import annotations

from collections import Counter

from app.core import db
from app.models import AuditEvent, Referral


def test_seed_builds_every_stage_through_the_api(database):
    from app import seed

    out = seed.seed()
    assert out["status"] == "seeded" and out["referrals"] == 16
    with db.session_factory()() as s:
        statuses = Counter(r.status for r in s.query(Referral))
        assert {
            "needs_review",
            "ready",
            "submitted",
            "acknowledged",
            "scheduled",
            "completed",
            "exception",
            "declined",
        } <= set(statuses)
        assert s.query(AuditEvent).count() > 100
    assert seed.seed()["status"] == "exists"
