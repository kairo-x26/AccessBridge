"""Database-backed durable job queue (NFR reliability).

* at-least-once: a job is leased, not removed; a crashed worker's lease expires and the job
  is claimed again, so handlers must be idempotent (they are: see agent action keys);
* claims are atomic compare-and-set UPDATEs, safe across processes on PostgreSQL and SQLite;
* failures retry with exponential backoff and land in ``dead`` after ``max_attempts``
  (dead-letter), which raises an operations task instead of failing silently.

The ``WorkflowEngine`` seam lets a Temporal-backed implementation replace this later.
"""

from __future__ import annotations

import logging
import socket
import traceback
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import session_factory, utcnow
from app.models import Job
from app.services import audit, tasks

log = logging.getLogger(__name__)
Handler = Callable[[Session, Job], dict[str, Any] | None]
_handlers: dict[str, Handler] = {}
# A hook returns True when it already surfaced the failure to people (no generic task).
DeadHook = Callable[[Session, Job, str], bool]
_dead_hooks: dict[str, DeadHook] = {}


class RetryableError(Exception):
    """Transient failure: the job is retried with backoff."""


class PermanentError(Exception):
    """Failure that retrying can't fix: the job is dead-lettered immediately."""


JOB_NAMES = {
    "agent.run": "An agent check",
    "agent.execute_action": "An approved action",
    "sweep.follow_up": "The follow-up sweep",
    "sweep.escalation": "The task escalation sweep",
}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return register


def on_dead(kind: str) -> Callable[[DeadHook], DeadHook]:
    """Register compensation to run when a job of this kind is dead-lettered."""

    def register(fn: DeadHook) -> DeadHook:
        _dead_hooks[kind] = fn
        return fn

    return register


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    organization_id: str | None,
    idempotency_key: str | None = None,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
) -> Job:
    """Add a job. With an idempotency key, an existing job with that key is returned instead."""
    if idempotency_key:
        existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing:
            return existing
    job = Job(
        organization_id=organization_id,
        kind=kind,
        payload=payload,
        idempotency_key=idempotency_key,
        run_after=run_after or utcnow(),
        max_attempts=max_attempts or get_settings().job_max_attempts,
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        found = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        assert found is not None
        return found
    return job


def claim(session: Session, worker_id: str, now: datetime | None = None) -> Job | None:
    now = now or utcnow()
    lease = timedelta(seconds=get_settings().job_lease_seconds)
    candidates = session.scalars(
        select(Job.id)
        .where(
            or_(
                (Job.status == "queued") & (Job.run_after <= now),
                (Job.status == "running") & (Job.lease_until < now),
            )
        )
        .order_by(Job.run_after)
        .limit(10)
    ).all()
    for job_id in candidates:
        res = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                or_(
                    (Job.status == "queued") & (Job.run_after <= now),
                    (Job.status == "running") & (Job.lease_until < now),
                ),
            )
            .values(
                status="running",
                locked_by=worker_id,
                lease_until=now + lease,
                attempts=Job.attempts + 1,
            )
            .execution_options(synchronize_session=False)
        )
        session.commit()
        if res.rowcount == 1:  # type: ignore[attr-defined]
            job = session.get(Job, job_id)
            if job is not None:
                session.refresh(job)
                return job
    return None


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 5 * 2 ** max(0, attempts - 1)))


def _dead_letter(session: Session, job: Job, error: str) -> None:
    job.status = "dead"
    job.finished_at = utcnow()
    job.last_error = error[:1000]
    audit.record(
        session,
        organization_id=job.organization_id,
        actor=f"system:job:{job.id}",
        operation="job.dead_letter",
        resource_ref=job.id,
        outcome="failed",
        details={"kind": job.kind, "attempts": job.attempts},
    )
    handled = False
    if hook := _dead_hooks.get(job.kind):
        handled = hook(session, job, error)
    if job.organization_id and not handled:
        tasks.ensure_task(
            session,
            organization_id=job.organization_id,
            referral_id=job.payload.get("referral_id"),
            kind="exception",
            priority="high",
            title="Automated step failed and needs a person",
            detail=f"{JOB_NAMES.get(job.kind, 'A background step')} failed after {job.attempts} "
            "attempts. Operations can see the technical error under failed jobs.",
            created_by=f"system:job:{job.id}",
            dedupe_key=f"dead-job:{job.id}",
        )


def run_job(job_id: str, worker_id: str) -> str:
    """Execute one claimed job in its own transaction. Returns the final status."""
    with session_factory()() as session:
        job = session.get(Job, job_id)
        assert job is not None
        fn = _handlers.get(job.kind)
        try:
            if fn is None:
                raise PermanentError(f"No handler for job kind {job.kind!r}")
            result = fn(session, job)
            job.status = "succeeded"
            job.result = result or {}
            job.finished_at = utcnow()
            job.last_error = None
            session.commit()
            return job.status
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, none is lost
            session.rollback()
            job = session.get(Job, job_id)
            assert job is not None
            error = f"{type(exc).__name__}: {exc}"
            log.warning(
                "job failed",
                extra={"fields": {"job_id": job.id, "kind": job.kind, "attempt": job.attempts}},
            )
            if isinstance(exc, PermanentError) or job.attempts >= job.max_attempts:
                if not isinstance(exc, PermanentError | RetryableError):
                    error += "\n" + traceback.format_exc(limit=3)
                _dead_letter(session, job, error)
            else:
                job.status = "queued"
                job.run_after = utcnow() + _backoff(job.attempts)
                job.last_error = error[:1000]
                job.locked_by = None
                job.lease_until = None
            session.commit()
            return job.status


def run_pending(limit: int = 100, worker_id: str | None = None, now: datetime | None = None) -> int:
    """Drain due jobs; returns the number executed. Used by the worker loop and tests."""
    worker_id = worker_id or f"{socket.gethostname()}:inline"
    done = 0
    while done < limit:
        with session_factory()() as session:
            job = claim(session, worker_id, now)
            if job is None:
                return done
            job_id = job.id
        run_job(job_id, worker_id)
        done += 1
    return done


def retry_dead(session: Session, job: Job) -> Job:
    job.status = "queued"
    job.attempts = 0
    job.run_after = utcnow()
    job.finished_at = None
    return job


def is_due(job: Job, now: datetime) -> bool:
    ra = _aware(job.run_after)
    return ra is not None and ra <= now
