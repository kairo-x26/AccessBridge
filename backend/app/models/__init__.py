"""Import every model so SQLAlchemy registers all mappers."""

from app.models.agents import AgentAction, AgentRun, Approval, ExchangeTransmission, Job, LLMUsage
from app.models.audit import AuditEvent
from app.models.intelligence import (
    ChecklistTemplate,
    ExtractedField,
    ReferralPackage,
    ValidationIssue,
)
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
    "AgentAction",
    "AgentRun",
    "Approval",
    "ExchangeTransmission",
    "Job",
    "LLMUsage",
    "AuditEvent",
    "ChecklistTemplate",
    "ExtractedField",
    "ReferralPackage",
    "ValidationIssue",
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
