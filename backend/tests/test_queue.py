from __future__ import annotations

from datetime import timedelta

from app.core import db
from app.core.db import utcnow
from app.models import Job, Task
from app.workers import queue
from tests.factories import make_org

calls: list[str] = []


@queue.handler("test.ok")
def _ok(session, job):
    calls.append(job.id)
    return {"n": len(calls)}


@queue.handler("test.flaky")
def _flaky(session, job):
    if job.attempts < 3:
        raise queue.RetryableError("not yet")
    return {"ok": True}


@queue.handler("test.broken")
def _broken(session, job):
    raise queue.PermanentError("bad input")


@queue.handler("test.crash")
def _crash(session, job):
    raise RuntimeError("boom")


def _enqueue(kind, org=None, **kw):
    with db.session_factory()() as s:
        j = queue.enqueue(s, kind, {}, organization_id=org, **kw)
        s.commit()
        return j.id


def _job(job_id):
    with db.session_factory()() as s:
        return s.get(Job, job_id)


def test_enqueue_is_idempotent_by_key(database):
    a = _enqueue("test.ok", idempotency_key="k1")
    b = _enqueue("test.ok", idempotency_key="k1")
    assert a == b


def test_claim_is_exclusive(database):
    _enqueue("test.ok")
    with db.session_factory()() as s1, db.session_factory()() as s2:
        first = queue.claim(s1, "w1")
        second = queue.claim(s2, "w2")
    assert first is not None and second is None


def test_expired_lease_is_reclaimed(database):
    jid = _enqueue("test.ok")
    with db.session_factory()() as s:
        assert queue.claim(s, "crashed-worker")
    later = utcnow() + timedelta(minutes=5)
    with db.session_factory()() as s:
        again = queue.claim(s, "w2", now=later)
    assert again is not None and again.id == jid and again.attempts == 2


def test_retry_with_backoff_then_success(database):
    jid = _enqueue("test.flaky")
    now = utcnow()
    for i in range(3):
        queue.run_pending(now=now + timedelta(hours=i))
    j = _job(jid)
    assert j.status == "succeeded" and j.attempts == 3


def test_backoff_delays_retry(database):
    jid = _enqueue("test.flaky")
    queue.run_pending()
    assert queue.run_pending() == 0  # not due yet
    assert _job(jid).status == "queued"


def test_dead_letter_creates_task(database):
    org = make_org()
    jid = _enqueue("test.crash", org=org, max_attempts=2)
    now = utcnow()
    queue.run_pending(now=now)
    queue.run_pending(now=now + timedelta(hours=1))
    j = _job(jid)
    assert j.status == "dead" and "boom" in j.last_error
    with db.session_factory()() as s:
        assert s.query(Task).filter(Task.dedupe_key == f"dead-job:{jid}").count() == 1


def test_permanent_error_dead_letters_immediately(database):
    jid = _enqueue("test.broken")
    queue.run_pending()
    assert _job(jid).status == "dead" and _job(jid).attempts == 1


def test_unknown_kind_is_dead(database):
    jid = _enqueue("test.nope")
    queue.run_pending()
    assert _job(jid).status == "dead"
