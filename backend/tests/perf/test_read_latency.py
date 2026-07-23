"""Read-path latency against the NFR target: p95 ordinary API reads under 500 ms.

Loads a few thousand referrals with tasks, events and documents directly, then times the
reads coordinators make all day. Run with `pytest -m perf`.
"""

from __future__ import annotations

import random
import statistics
import time
from datetime import timedelta

import pytest

from app.core import db
from app.core.db import utcnow
from app.models import PatientReference, Referral, ReferralStatusEvent, Task
from tests.factories import make_org, make_user

pytestmark = pytest.mark.perf

N_REFERRALS = 3000
STATUSES = [
    "needs_review",
    "ready",
    "submitted",
    "acknowledged",
    "scheduled",
    "completed",
    "exception",
]
SPECIALTIES = ["cardiology", "dermatology", "neurology", "orthopedics", "endocrinology"]


def _load(org: str, owner: str) -> list[str]:
    rng = random.Random(1)  # noqa: S311
    ids = []
    with db.session_factory()() as s:
        now = utcnow()
        for i in range(N_REFERRALS):
            p = PatientReference(
                organization_id=org,
                ehr_patient_id=f"P{i:06d}",
                given_name=f"Given{i}",
                family_name=f"Family{i % 400}",
            )
            s.add(p)
            s.flush()
            status = rng.choice(STATUSES)
            created = now - timedelta(days=rng.randint(0, 90))
            r = Referral(
                organization_id=org,
                patient_ref_id=p.id,
                source_system="fhir",
                source_id=f"SR{i}",
                specialty=rng.choice(SPECIALTIES),
                status=status,
                progress_status=status if status != "exception" else "ready",
                owner_id=owner if i % 3 else None,
                created_at=created,
                status_changed_at=created,
            )
            s.add(r)
            s.flush()
            ids.append(r.id)
            for st in ("imported", "needs_review", status):
                s.add(
                    ReferralStatusEvent(
                        organization_id=org,
                        referral_id=r.id,
                        new_status=st,
                        actor="system:perf",
                        timestamp=created,
                    )
                )
            if i % 2:
                s.add(
                    Task(
                        organization_id=org,
                        referral_id=r.id,
                        kind="follow_up",
                        title="Follow up",
                        created_by="system:perf",
                        due_at=now - timedelta(days=rng.randint(-5, 5)),
                    )
                )
        s.commit()
    return ids


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[18]


def test_ordinary_reads_meet_p95_target(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    admin = make_user(org, "admin")
    ids = _load(org, coord.user_id)
    h, ha = coord.headers(), admin.headers()
    reads = {
        "queue page": lambda i: client.get(
            "/v1/referrals?status=needs_review&status=exception&page=2", headers=h
        ),
        "queue search": lambda i: client.get(f"/v1/referrals?q=family{i % 400}", headers=h),
        "referral detail": lambda i: client.get(
            f"/v1/referrals/{ids[i * 37 % len(ids)]}", headers=h
        ),
        "my tasks": lambda i: client.get("/v1/tasks?owner=me", headers=h),
        "overdue tasks": lambda i: client.get("/v1/tasks?overdue=true", headers=h),
        "dashboard metrics": lambda i: client.get("/v1/reports/referrals", headers=ha),
    }
    results = {}
    for name, call in reads.items():
        call(0)  # warm-up
        samples = []
        for i in range(40):
            t = time.perf_counter()
            r = call(i)
            samples.append(time.perf_counter() - t)
            assert r.status_code == 200, (name, r.text[:200])
        results[name] = _p95(samples) * 1000
    print("\np95 ms:", {k: round(v, 1) for k, v in results.items()})
    for name, ms in results.items():
        assert ms < 500, f"{name}: p95 {ms:.0f} ms"
