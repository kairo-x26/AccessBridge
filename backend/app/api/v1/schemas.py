"""Shared response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class PatientOut(BaseModel):
    id: str
    ehr_patient_id: str
    display_name: str
    preferred_language: str
    preferred_channel: str
    # Contact details only for roles that coordinate outreach.
    birth_date: str | None = None
    phone: str | None = None
    email: str | None = None
    contact_verified: bool = False
    opted_out: bool = False
    needs_interpreter: bool = False
    transportation_need: bool = False


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    specialty: str
    network_reference: str | None
    location: str | None
    contact_method: str
    phone: str | None
    accepts_referrals: bool
    languages: list[str]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size_bytes: int
    checksum: str
    doc_type: str
    doc_type_confidence: float | None
    source_system: str
    extraction_status: str
    created_at: datetime


class StatusEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    old_status: str | None
    new_status: str
    evidence_type: str | None
    evidence_reference: str | None
    reason: str | None
    actor: str
    correction: bool
    timestamp: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    referral_id: str | None
    kind: str
    title: str
    detail: str | None
    status: str
    priority: str
    owner_id: str | None
    due_at: datetime | None
    escalation_level: int
    created_by: str
    created_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    data: dict[str, Any]


class ReferralSummary(BaseModel):
    id: str
    status: str
    progress_status: str
    specialty: str
    priority_from_source: str
    patient_name: str
    patient_ehr_id: str
    provider_name: str | None
    owner_id: str | None
    owner_name: str | None
    source_system: str
    source_id: str
    age_days: int
    open_tasks: int
    created_at: datetime
    status_changed_at: datetime
    appointment_at: datetime | None
    version: int


class TransitionOption(BaseModel):
    status: str
    accepted_evidence: list[str] | None
    reason_required: bool


class ReferralDetail(ReferralSummary):
    reason_from_source: str | None
    referring_clinician: str | None
    exception_reason: str | None
    legal_hold: bool
    purged_at: datetime | None
    package_approved_by: str | None
    package_approved_at: datetime | None
    patient: PatientOut
    provider: ProviderOut | None
    documents: list[DocumentOut]
    events: list[StatusEventOut]
    tasks: list[TaskOut]
    next_statuses: list[TransitionOption]
