from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedString
from app.core.db import Base, TimestampMixin, new_id, utcnow


class MessageTemplate(TimestampMixin, Base):
    """Organization-approved patient message wording (FR-11, FR-15)."""

    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("organization_id", "key", "language", "version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tpl"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(10))
    version: Mapped[int]
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(80))
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None]
    active: Mapped[bool] = mapped_column(default=False)


class Communication(TimestampMixin, Base):
    __tablename__ = "communications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("msg"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str | None] = mapped_column(ForeignKey("referrals.id"), index=True)
    patient_ref_id: Mapped[str | None] = mapped_column(ForeignKey("patient_references.id"))
    direction: Mapped[str] = mapped_column(String(10))  # outbound | inbound
    channel: Mapped[str] = mapped_column(String(10))  # sms | email
    template_key: Mapped[str | None] = mapped_column(String(60))
    template_id: Mapped[str | None] = mapped_column(ForeignKey("message_templates.id"))
    language: Mapped[str | None] = mapped_column(String(10))
    body: Mapped[str | None] = mapped_column(EncryptedString(4000))
    address: Mapped[str | None] = mapped_column(EncryptedString(400))
    # Keyed hash of the normalized address so replies can be matched without decrypting.
    address_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    consent_reference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(120), index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    classification: Mapped[str | None] = mapped_column(String(30))
    classified_by: Mapped[str | None] = mapped_column(String(20))
    escalated: Mapped[bool] = mapped_column(default=False)
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[str | None] = mapped_column(String(80))
    in_reply_to: Mapped[str | None] = mapped_column(ForeignKey("communications.id"))
    action_id: Mapped[str | None] = mapped_column(ForeignKey("agent_actions.id"))
    created_by: Mapped[str] = mapped_column(String(80))
    sent_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)


class Notification(Base):
    """In-app notice to a role or user, e.g. the clinical team when care is completed."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ntf"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    audience_role: Mapped[str | None] = mapped_column(String(40))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    referral_id: Mapped[str | None] = mapped_column(ForeignKey("referrals.id"))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    read_by: Mapped[list[str]] = mapped_column(JSON, default=list)
