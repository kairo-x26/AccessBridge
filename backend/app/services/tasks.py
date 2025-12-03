"""Coordinator task queue (FR-08): idempotent creation, assignment and escalation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import Task
from app.services import audit

OPEN_STATES = ("open", "in_progress")
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
# Default time to act by task kind (administrative service levels, configurable later).
DEFAULT_DUE = {
    "missing_info": timedelta(days=2),
    "review_package": timedelta(days=1),
    "approval": timedelta(hours=8),
    "follow_up": timedelta(days=3),
    "exception": timedelta(days=1),
    "patient_assistance": timedelta(days=1),
    "reconciliation": timedelta(days=1),
    "escalation": timedelta(hours=4),
}


def ensure_task(
    session: Session,
    *,
    organization_id: str,
    kind: str,
    title: str,
    created_by: str,
    referral_id: str | None = None,
    detail: str | None = None,
    priority: str = "normal",
    owner_id: str | None = None,
    due_at: datetime | None = None,
    dedupe_key: str | None = None,
    data: dict[str, Any] | None = None,
) -> tuple[Task, bool]:
    """Create a task unless an open task has the same dedupe key. Returns (task, created)."""
    if dedupe_key:
        existing = session.scalar(
            select(Task).where(
                Task.organization_id == organization_id,
                Task.dedupe_key == dedupe_key,
                Task.status.in_(OPEN_STATES),
            )
        )
        if existing:
            return existing, False
    task = Task(
        organization_id=organization_id,
        referral_id=referral_id,
        kind=kind,
        title=title,
        detail=detail,
        priority=priority,
        owner_id=owner_id,
        due_at=due_at or utcnow() + DEFAULT_DUE.get(kind, timedelta(days=2)),
        created_by=created_by,
        dedupe_key=dedupe_key,
        data=data or {},
    )
    session.add(task)
    session.flush()
    audit.record(
        session,
        organization_id=organization_id,
        actor=created_by,
        operation="task.create",
        resource_ref=task.id,
        details={"kind": kind, "referral_id": referral_id},
    )
    return task, True


def resolve(
    session: Session, task: Task, *, actor: str, resolution: str, status: str = "done"
) -> Task:
    if task.status in OPEN_STATES:
        task.status = status
        task.resolved_at = utcnow()
        task.resolution = resolution
        audit.record(
            session,
            organization_id=task.organization_id,
            actor=actor,
            operation="task.resolve",
            resource_ref=task.id,
            details={"status": status},
        )
    return task


def resolve_by_key(
    session: Session, organization_id: str, dedupe_key: str, *, actor: str, resolution: str
) -> int:
    tasks = session.scalars(
        select(Task).where(
            Task.organization_id == organization_id,
            Task.dedupe_key == dedupe_key,
            Task.status.in_(OPEN_STATES),
        )
    ).all()
    for t in tasks:
        resolve(session, t, actor=actor, resolution=resolution)
    return len(tasks)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def escalate_overdue(session: Session, *, now: datetime | None = None) -> list[Task]:
    """Raise priority of overdue open tasks one step at a time; at most once per 24 hours."""
    now = now or utcnow()
    escalated = []
    for task in session.scalars(
        select(Task).where(Task.status.in_(OPEN_STATES), Task.due_at.is_not(None))
    ):
        assert task.due_at is not None
        if _aware(task.due_at) > now:
            continue
        if task.escalated_at and now - _aware(task.escalated_at) < timedelta(hours=24):
            continue
        task.escalation_level += 1
        task.escalated_at = now
        order = ["low", "normal", "high", "urgent"]
        task.priority = order[min(order.index(task.priority) + 1, len(order) - 1)]
        audit.record(
            session,
            organization_id=task.organization_id,
            actor="system:escalation",
            operation="task.escalate",
            resource_ref=task.id,
            details={"level": task.escalation_level, "priority": task.priority},
        )
        escalated.append(task)
    return escalated
