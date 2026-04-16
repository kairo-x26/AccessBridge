"""Worker process: runs due jobs and schedules periodic sweeps.

Run: ``uv run python -m app.workers.run`` (one or more processes; claims are atomic).
"""

from __future__ import annotations

import logging
import signal
import socket
import time
from datetime import datetime

from app.core import db
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.logging import setup_logging
from app.workers import queue

log = logging.getLogger("worker")
SWEEPS = {
    # kind: bucket format (one job per bucket across all workers)
    "sweep.escalation": "%Y-%m-%dT%H:%M",  # every minute
    "sweep.follow_up": "%Y-%m-%dT%H",  # hourly
}


def register_handlers() -> None:
    import app.agents.orchestrator  # noqa: F401
    import app.services.notifications  # noqa: F401


def schedule_sweeps(now: datetime | None = None) -> None:
    now = now or utcnow()
    with db.session_factory()() as session:
        for kind, fmt in SWEEPS.items():
            bucket = now.strftime(fmt)
            queue.enqueue(
                session,
                kind,
                {"bucket": bucket},
                organization_id=None,
                idempotency_key=f"{kind}:{bucket}",
                max_attempts=1,
            )
        session.commit()


def main() -> None:
    setup_logging(get_settings().log_level)
    register_handlers()
    worker_id = f"{socket.gethostname()}:{int(time.time())}"
    stop = False

    def _stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started", extra={"fields": {"worker_id": worker_id}})
    while not stop:
        schedule_sweeps()
        if queue.run_pending(limit=50, worker_id=worker_id) == 0:
            time.sleep(1.0)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
