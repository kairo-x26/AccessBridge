"""Secure document exchange adapter for transmitting approved referral packages.

The simulated transport stands in for Direct messaging / a vendor referral network. Failure
modes are selected by the provider endpoint so workflows can be exercised end to end:

* ``sim://ok`` (default) — accepted with a receipt;
* ``sim://flaky`` — the first attempt fails transiently, later attempts succeed;
* ``sim://down`` — always fails transiently (exercises retries and dead-lettering);
* ``sim://reject`` — permanently rejected by the receiving system.

Transmission is idempotent per key: a retried send returns the original receipt and never
sends twice. An unavailable system never produces a success.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.models import ExchangeTransmission, ExternalProvider, ReferralPackage


class TransientSendError(Exception):
    pass


class PermanentSendError(Exception):
    pass


@dataclass
class Receipt:
    receipt_id: str
    duplicate: bool


class SimulatedReceiver:
    """The receiving system's own memory. It lives outside our database transaction, as a
    real remote system would, and deduplicates by message idempotency key."""

    def __init__(self) -> None:
        self.received: dict[str, str] = {}
        self.calls: dict[str, int] = {}

    def deliver(self, key: str, mode: str) -> Receipt:
        self.calls[key] = self.calls.get(key, 0) + 1
        if mode == "down" or (mode == "flaky" and self.calls[key] == 1):
            raise TransientSendError("Receiving system unavailable")
        if mode == "reject":
            raise PermanentSendError("Receiving system rejected the package")
        if key in self.received:
            return Receipt(self.received[key], duplicate=True)
        receipt = "rcpt_" + hashlib.sha256(key.encode()).hexdigest()[:16]
        self.received[key] = receipt
        return Receipt(receipt, duplicate=False)


receiver = SimulatedReceiver()


def send_package(
    session: Session, *, package: ReferralPackage, provider: ExternalProvider, idempotency_key: str
) -> Receipt:
    row = session.scalar(
        select(ExchangeTransmission).where(ExchangeTransmission.idempotency_key == idempotency_key)
    )
    if row and row.status == "sent" and row.receipt_id:
        return Receipt(row.receipt_id, duplicate=True)
    if row is None:
        row = ExchangeTransmission(
            organization_id=package.organization_id,
            idempotency_key=idempotency_key,
            referral_id=package.referral_id,
            package_id=package.id,
            provider_id=provider.id,
            status="failed",
            attempts=0,
        )
        session.add(row)
    row.attempts += 1
    mode = (provider.endpoint or "sim://ok").removeprefix("sim://")
    if provider.contact_method == "fax" and not provider.phone:
        mode = "reject"
    try:
        receipt = receiver.deliver(idempotency_key, mode)
    except (TransientSendError, PermanentSendError) as exc:
        row.last_error = str(exc)
        session.flush()
        raise
    row.status, row.receipt_id, row.sent_at, row.last_error = (
        "sent",
        receipt.receipt_id,
        utcnow(),
        None,
    )
    session.flush()
    return receipt
