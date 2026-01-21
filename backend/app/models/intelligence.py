from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedString
from app.core.db import Base, TimestampMixin, new_id, utcnow


class ExtractedField(TimestampMixin, Base):
    """A candidate administrative value with a link to the exact source text (FR-05)."""

    __tablename__ = "extracted_fields"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fld"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("referral_documents.id"))
    name: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(EncryptedString(2000))
    span_start: Mapped[int]
    span_end: Mapped[int]
    confidence: Mapped[float]
    method: Mapped[str] = mapped_column(String(20))  # pattern | llm
    critical: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    corrected_value: Mapped[str | None] = mapped_column(EncryptedString(2000))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]
    extraction_version: Mapped[str] = mapped_column(String(40))

    @property
    def effective_value(self) -> str | None:
        if self.status == "rejected":
            return None
        return self.corrected_value if self.status == "corrected" else self.value


class ChecklistTemplate(TimestampMixin, Base):
    """Organization-specific checklist overriding the built-in one for a specialty (FR-20)."""

    __tablename__ = "checklist_templates"
    __table_args__ = (UniqueConstraint("organization_id", "specialty", "version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("chk"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    specialty: Mapped[str] = mapped_column(String(60))
    version: Mapped[int]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    updated_by: Mapped[str] = mapped_column(String(80))


class ValidationIssue(TimestampMixin, Base):
    __tablename__ = "validation_issues"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("vis"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))  # blocking | warning
    message: Mapped[str] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|resolved|waived
    resolved_by: Mapped[str | None] = mapped_column(String(80))
    resolution: Mapped[str | None] = mapped_column(String(400))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))


class ReferralPackage(Base):
    """Immutable snapshot of what a coordinator approved for transmission (FR-07)."""

    __tablename__ = "referral_packages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pkg"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    version: Mapped[int]
    contents: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)
