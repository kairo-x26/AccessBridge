"""Patient messaging adapter (simulated SMS gateway) and webhook signing.

The simulated gateway behaves like a real provider: it remembers sends by idempotency key
outside our transaction, rejects invalid numbers, and has an outage mode. Numbers ending in
0000 are invalid; numbers ending in 9999 hit a provider outage.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings


class TransientMessagingError(Exception):
    pass


class PermanentMessagingError(Exception):
    pass


@dataclass
class SimulatedGateway:
    sent: dict[str, str] = field(default_factory=dict)  # idempotency key -> message id
    outbox: list[dict[str, str]] = field(default_factory=list)

    def send(self, *, to: str, body: str, idempotency_key: str) -> tuple[str, bool]:
        digits = "".join(c for c in to if c.isdigit())
        if len(digits) < 10 or digits.endswith("0000"):
            raise PermanentMessagingError("The phone number isn't valid for text messages.")
        if digits.endswith("9999"):
            raise TransientMessagingError("Messaging provider is unavailable.")
        if idempotency_key in self.sent:
            return self.sent[idempotency_key], True
        mid = "sm_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:18]
        self.sent[idempotency_key] = mid
        self.outbox.append({"id": mid, "to": to, "body": body})
        return mid, False


gateway = SimulatedGateway()


def sign(body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = str(timestamp or int(time.time()))
    secret = get_settings().messaging_webhook_secret.encode()
    sig = hmac.new(secret, ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"x-ab-timestamp": ts, "x-ab-signature": sig}


def verify(body: bytes, timestamp: str | None, signature: str | None, tolerance: int = 300) -> bool:
    if not timestamp or not signature or not timestamp.isdigit():
        return False
    if abs(time.time() - int(timestamp)) > tolerance:
        return False
    expected = sign(body, int(timestamp))["x-ab-signature"]
    return hmac.compare_digest(expected, signature)


def event(kind: str, **fields: Any) -> bytes:
    """Build a webhook payload as the provider would (used by tests and the demo)."""
    return json.dumps({"type": kind, **fields}).encode()
