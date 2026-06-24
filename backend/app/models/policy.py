from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class PolicyDocument(TimestampMixin, Base):
    """A clinic procedure. Only approved versions are searchable (FR-14)."""

    __tablename__ = "policy_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pol"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|archived
    content: Mapped[str] = mapped_column(Text)
    source_filename: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[str] = mapped_column(String(80))
    approved_by: Mapped[str | None] = mapped_column(String(80))
    approved_at: Mapped[datetime | None]
    flagged_passages: Mapped[int] = mapped_column(default=0)


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("pch"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("policy_documents.id"), index=True)
    ordinal: Mapped[int]
    heading: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    # Passages that look like instructions to an AI are kept for people but never sent to a model.
    flagged: Mapped[bool] = mapped_column(default=False)
