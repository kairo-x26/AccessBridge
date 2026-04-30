from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedString
from app.core.db import Base, TimestampMixin, new_id, utcnow


class PatientReference(TimestampMixin, Base):
    """Minimum patient identity and contact data needed for administrative coordination."""

    __tablename__ = "patient_references"
    __table_args__ = (UniqueConstraint("organization_id", "ehr_patient_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pat"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    ehr_patient_id: Mapped[str] = mapped_column(String(80))
    given_name: Mapped[str] = mapped_column(String(100))
    family_name: Mapped[str] = mapped_column(String(100), index=True)
    birth_date: Mapped[str | None] = mapped_column(EncryptedString(255))
    phone: Mapped[str | None] = mapped_column(EncryptedString(255))
    email: Mapped[str | None] = mapped_column(EncryptedString(400))
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    preferred_channel: Mapped[str] = mapped_column(String(20), default="sms")  # sms|email|phone
    contact_verified: Mapped[bool] = mapped_column(default=False)
    consent_reference: Mapped[str | None] = mapped_column(String(120))
    opted_out_at: Mapped[datetime | None]
    needs_interpreter: Mapped[bool] = mapped_column(default=False)
    transportation_need: Mapped[bool] = mapped_column(default=False)

    @property
    def display_name(self) -> str:
        return f"{self.given_name} {self.family_name}"


class ExternalProvider(TimestampMixin, Base):
    __tablename__ = "external_providers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prv"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    specialty: Mapped[str] = mapped_column(String(60), index=True)
    network_reference: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(200))
    contact_method: Mapped[str] = mapped_column(String(20), default="direct")  # fhir|direct|fax
    endpoint: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(40))
    accepts_referrals: Mapped[bool] = mapped_column(default=True)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list)


class Referral(TimestampMixin, Base):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("organization_id", "source_system", "source_id"),
        Index("ix_referrals_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ref"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    patient_ref_id: Mapped[str] = mapped_column(ForeignKey("patient_references.id"), index=True)
    source_system: Mapped[str] = mapped_column(String(60))
    source_id: Mapped[str] = mapped_column(String(120))
    specialty: Mapped[str] = mapped_column(String(60), index=True)
    # Priority exactly as stated by the referring source. The platform never sets urgency.
    priority_from_source: Mapped[str] = mapped_column(String(20), default="routine")
    reason_from_source: Mapped[str | None] = mapped_column(Text)
    referring_clinician: Mapped[str | None] = mapped_column(String(200))
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("external_providers.id"))
    status: Mapped[str] = mapped_column(String(20), default="imported")
    # Furthest point reached on the route; kept when the referral leaves it (exception,
    # declined, cancelled) so the UI can show where it branched off.
    progress_status: Mapped[str] = mapped_column(String(20), default="imported")
    status_changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    package_approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    package_approved_at: Mapped[datetime | None]
    external_task_id: Mapped[str | None] = mapped_column(String(120))
    appointment_at: Mapped[datetime | None]
    exception_reason: Mapped[str | None] = mapped_column(String(300))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=1)

    patient: Mapped[PatientReference] = relationship(lazy="joined")
    provider: Mapped[ExternalProvider | None] = relationship(lazy="joined")


class ReferralDocument(TimestampMixin, Base):
    __tablename__ = "referral_documents"
    __table_args__ = (UniqueConstraint("referral_id", "checksum"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("doc"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_uri: Mapped[str] = mapped_column(String(400))
    checksum: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    doc_type: Mapped[str] = mapped_column(String(40), default="unclassified")
    doc_type_confidence: Mapped[float | None]
    source_system: Mapped[str] = mapped_column(String(60))
    uploaded_by: Mapped[str | None] = mapped_column(String(80))
    text_content: Mapped[str | None] = mapped_column(EncryptedString(2_000_000))
    extraction_status: Mapped[str] = mapped_column(String(20), default="pending")


class ReferralStatusEvent(Base):
    __tablename__ = "referral_status_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evt"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20))
    evidence_type: Mapped[str | None] = mapped_column(String(60))
    evidence_reference: Mapped[str | None] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(80))
    correction: Mapped[bool] = mapped_column(default=False)
    timestamp: Mapped[datetime] = mapped_column(default=utcnow)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_org_status_owner", "organization_id", "status", "owner_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tsk"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str | None] = mapped_column(ForeignKey("referrals.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime | None]
    escalation_level: Mapped[int] = mapped_column(default=0)
    escalated_at: Mapped[datetime | None]
    created_by: Mapped[str] = mapped_column(String(80))
    # Open tasks with the same key are the same piece of work; creation is idempotent.
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[str | None] = mapped_column(String(500))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("organization_id", "key", "endpoint"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("idm"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    key: Mapped[str] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int]
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class IntegrationEvent(Base):
    """Inbound integration message, kept for deduplication and reconciliation (FR-19)."""

    __tablename__ = "integration_events"
    __table_args__ = (UniqueConstraint("organization_id", "source", "external_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ine"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source: Mapped[str] = mapped_column(String(60))
    external_id: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(60))
    referral_id: Mapped[str | None] = mapped_column(ForeignKey("referrals.id"))
    outcome: Mapped[str] = mapped_column(String(30))  # applied|duplicate|stale|conflict|unmatched
    detail: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
