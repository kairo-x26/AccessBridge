"""In-process sliding-window rate limiter.

Good for a single API instance and for tests; a multi-instance deployment should back this
with Redis (spec §10 lists Redis for throttling). The interface stays the same.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.errors import RateLimited


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: int, window_s: float, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_s - (now - q[0])) + 1
                raise RateLimited(
                    "Too many attempts. Wait a moment and try again.",
                    details={"retry_after_seconds": retry},
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindow()


def client_ip(request: object) -> str:
    from fastapi import Request

    from app.core.config import get_settings

    assert isinstance(request, Request)
    if get_settings().trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit(key: str, *, limit: int, window_s: float) -> None:
    from app.core.config import get_settings

    if get_settings().rate_limits_enabled:
        limiter.check(key, limit=limit, window_s=window_s)
