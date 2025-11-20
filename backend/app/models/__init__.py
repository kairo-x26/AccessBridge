"""Import every model so SQLAlchemy registers all mappers."""

from app.models.audit import AuditEvent
from app.models.organization import Organization
from app.models.referral import (
    ExternalProvider,
    IdempotencyRecord,
    IntegrationEvent,
    PatientReference,
    Referral,
    ReferralDocument,
    ReferralStatusEvent,
    Task,
)
from app.models.user import Invitation, User

__all__ = [
    "AuditEvent",
    "ExternalProvider",
    "IdempotencyRecord",
    "IntegrationEvent",
    "Invitation",
    "Organization",
    "PatientReference",
    "Referral",
    "ReferralDocument",
    "ReferralStatusEvent",
    "Task",
    "User",
]
