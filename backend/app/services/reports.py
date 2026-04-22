"""Operational metrics (FR-17, FR-21) with one set of written definitions.

Everything here is aggregate. Definitions are returned alongside the numbers so dashboards,
exports and pilots measure the same thing (spec §7: "consistent definitions").
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.domain.state_machine import TERMINAL, Status
from app.models import (
    AgentAction,
    LLMUsage,
    Referral,
    ReferralStatusEvent,
    Task,
    User,
)
from app.services.tasks import OPEN_STATES

DEFINITIONS = {
    "open": "Not completed, declined or cancelled.",
    "age_days": "Days since the referral was imported.",
    "visibility": "Share of open referrals with an assigned owner and a status set by an "
    "evidence-backed event within the last 30 days.",
    "completed_care_rate": "Share of referrals imported in the window that reached "
    "'completed' with consult-note or specialist evidence. Scheduling "
    "and message delivery do not count.",
    "days_to_submitted": "Median days from import to the 'submitted' event.",
    "days_to_completed": "Median days from import to the 'completed' event.",
    "agent_acceptance_rate": "Share of agent proposals needing approval that staff approved.",
    "overdue_task": "Open task whose due time has passed.",
}

AGE_BUCKETS = (
    (0, 7, "0–7 days"),
    (8, 14, "8–14 days"),
    (15, 30, "15–30 days"),
    (31, 60, "31–60 days"),
    (61, 10**6, "Over 60 days"),
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class Filters:
    specialty: str | None = None
    owner_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass
class Report:
    generated_at: datetime
    filters: dict[str, Any]
    totals: dict[str, Any]
    status_distribution: dict[str, int]
    age_buckets: list[dict[str, Any]]
    by_specialty: list[dict[str, Any]]
    by_owner: list[dict[str, Any]]
    agent: dict[str, Any]
    model_usage: list[dict[str, Any]]
    definitions: dict[str, str] = field(default_factory=lambda: DEFINITIONS)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def build(session: Session, organization_id: str, f: Filters) -> Report:
    now = utcnow()
    q = select(Referral).where(Referral.organization_id == organization_id)
    if f.specialty:
        q = q.where(Referral.specialty == f.specialty)
    if f.owner_id:
        q = q.where(Referral.owner_id == f.owner_id)
    if f.since:
        q = q.where(Referral.created_at >= f.since)
    if f.until:
        q = q.where(Referral.created_at < f.until)
    refs = list(session.scalars(q))
    ids = [r.id for r in refs]
    events: dict[str, list[ReferralStatusEvent]] = defaultdict(list)
    if ids:
        for e in session.scalars(
            select(ReferralStatusEvent)
            .where(ReferralStatusEvent.referral_id.in_(ids))
            .order_by(ReferralStatusEvent.timestamp)
        ):
            events[e.referral_id].append(e)
    open_refs = [r for r in refs if Status(r.status) not in TERMINAL]

    status_dist = Counter(r.status for r in refs)
    buckets = []
    for lo, hi, label in AGE_BUCKETS:
        n = sum(1 for r in open_refs if lo <= (now - _aware(r.created_at)).days <= hi)
        buckets.append({"label": label, "count": n})

    def first(rid: str, status: str) -> datetime | None:
        return next((_aware(e.timestamp) for e in events[rid] if e.new_status == status), None)

    to_submitted = [
        ((t - _aware(r.created_at)).total_seconds() / 86400)
        for r in refs
        if (t := first(r.id, "submitted"))
    ]
    to_completed = [
        ((t - _aware(r.created_at)).total_seconds() / 86400)
        for r in refs
        if (t := first(r.id, "completed"))
    ]
    completion_evidence = {"consult_note", "specialist_completion_confirmation", "fhir_task_update"}
    completed_verified = sum(
        1
        for r in refs
        if r.status == "completed"
        and any(
            e.new_status == "completed" and e.evidence_type in completion_evidence
            for e in events[r.id]
        )
    )
    recent = now - timedelta(days=30)
    visible = sum(
        1
        for r in open_refs
        if r.owner_id and events[r.id] and _aware(events[r.id][-1].timestamp) >= recent
    )

    task_q = select(Task).where(
        Task.organization_id == organization_id, Task.status.in_(OPEN_STATES)
    )
    open_tasks = list(session.scalars(task_q))
    overdue = [t for t in open_tasks if t.due_at and _aware(t.due_at) < now]

    spec_rows: dict[str, Counter[str]] = defaultdict(Counter)
    for r in refs:
        c = spec_rows[r.specialty]
        c["total"] += 1
        c["open"] += Status(r.status) not in TERMINAL
        c["completed"] += r.status == "completed"
        c["exceptions"] += r.status == "exception"
    by_specialty = [
        {"specialty": s, **c, "completion_rate": round(c["completed"] / c["total"], 3)}
        for s, c in sorted(spec_rows.items())
    ]

    names = {
        u.id: u.full_name
        for u in session.scalars(select(User).where(User.organization_id == organization_id))
    }
    owner_rows: dict[str | None, Counter[str]] = defaultdict(Counter)
    for r in open_refs:
        owner_rows[r.owner_id]["open_referrals"] += 1
    for task in open_tasks:
        owner_rows[task.owner_id]["open_tasks"] += 1
        owner_rows[task.owner_id]["overdue_tasks"] += task in overdue
    by_owner = [
        {"owner_id": o, "owner_name": names.get(o or "", "Unassigned"), **c}
        for o, c in sorted(owner_rows.items(), key=lambda kv: -kv[1]["open_referrals"])
    ]

    actions = list(
        session.scalars(
            select(AgentAction).where(
                AgentAction.organization_id == organization_id,
                *(
                    [AgentAction.referral_id.in_(ids)]
                    if (f.specialty or f.owner_id or f.since or f.until)
                    else []
                ),
            )
        )
    )
    decisions = Counter(a.decision for a in actions)
    gated = [a for a in actions if a.decision == "approval_required"]
    approved = sum(
        1 for a in gated if a.status in ("approved", "succeeded", "skipped", "failed", "executing")
    )
    rejected = sum(1 for a in gated if a.status == "rejected")
    usage_rows: dict[str, Counter[str]] = defaultdict(Counter)
    for u in session.scalars(select(LLMUsage).where(LLMUsage.organization_id == organization_id)):
        c = usage_rows[u.task]
        c["calls"] += 1
        c["input_tokens"] += u.input_tokens
        c["output_tokens"] += u.output_tokens
        c["errors"] += u.outcome != "ok"

    return Report(
        generated_at=now,
        filters={
            "specialty": f.specialty,
            "owner_id": f.owner_id,
            "since": f.since.isoformat() if f.since else None,
            "until": f.until.isoformat() if f.until else None,
        },
        totals={
            "referrals": len(refs),
            "open": len(open_refs),
            "exceptions": status_dist.get("exception", 0),
            "completed": status_dist.get("completed", 0),
            "completed_care_rate": round(completed_verified / len(refs), 3) if refs else None,
            "visibility": round(visible / len(open_refs), 3) if open_refs else None,
            "unassigned_open": sum(1 for r in open_refs if not r.owner_id),
            "open_tasks": len(open_tasks),
            "overdue_tasks": len(overdue),
            "median_days_to_submitted": _median(to_submitted),
            "median_days_to_completed": _median(to_completed),
        },
        status_distribution={s.value: status_dist.get(s.value, 0) for s in Status},
        age_buckets=buckets,
        by_specialty=by_specialty,
        by_owner=by_owner,
        agent={
            "proposals": len(actions),
            "by_decision": dict(decisions),
            "approved": approved,
            "rejected": rejected,
            "acceptance_rate": round(approved / (approved + rejected), 3)
            if approved + rejected
            else None,
        },
        model_usage=[{"task": k, **v} for k, v in sorted(usage_rows.items())],
    )
