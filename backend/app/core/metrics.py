"""Minimal Prometheus metrics (NFR observability) without extra dependencies."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
Labels = tuple[tuple[str, str], ...]


def _fmt(name: str, labels: Labels, value: float) -> str:
    lab = ",".join(f'{k}="{v}"' for k, v in labels)
    return f"{name}{{{lab}}} {value}" if lab else f"{name} {value}"


def _empty_buckets() -> list[int]:
    return [0] * (len(BUCKETS) + 1)


class Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self.latency: dict[tuple[str, str], list[int]] = defaultdict(_empty_buckets)
        self.latency_sum: dict[tuple[str, str], float] = defaultdict(float)

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self.requests[(method, route, str(status))] += 1
            buckets = self.latency[(method, route)]
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    buckets[i] += 1
            buckets[-1] += 1
            self.latency_sum[(method, route)] += seconds

    def render(self, gauges: Mapping[str, Mapping[Any, float]]) -> str:
        req, hist = "accessbridge_http_requests_total", "accessbridge_http_request_seconds"
        lines = [f"# TYPE {req} counter"]
        with self._lock:
            for (m, r, s), n in sorted(self.requests.items()):
                lines.append(_fmt(req, (("method", m), ("route", r), ("status", s)), n))
            lines.append(f"# TYPE {hist} histogram")
            for (m, r), buckets in sorted(self.latency.items()):
                base = (("method", m), ("route", r))
                for b, n in zip((*BUCKETS, "+Inf"), buckets, strict=True):
                    lines.append(_fmt(f"{hist}_bucket", (*base, ("le", str(b))), n))
                lines.append(_fmt(f"{hist}_count", base, buckets[-1]))
                lines.append(_fmt(f"{hist}_sum", base, round(self.latency_sum[(m, r)], 4)))
        for name, series in gauges.items():
            lines.append(f"# TYPE {name} gauge")
            for labels, value in sorted(series.items()):
                lines.append(_fmt(name, labels, value))
        return "\n".join(lines) + "\n"


registry = Registry()
