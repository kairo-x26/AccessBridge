"""Import every model so SQLAlchemy registers all mappers."""

from app.models.agents import AgentAction, AgentRun, Approval, ExchangeTransmission, Job, LLMUsage
from app.models.audit import AuditEvent
from app.models.communication import Communication, MessageTemplate, Notification
from app.models.intelligence import (
    ChecklistTemplate,
    ExtractedField,
    ReferralPackage,
    ValidationIssue,
)
from app.models.organization import Organization
from app.models.policy import PolicyChunk, PolicyDocument
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
    "MessageTemplate",
    "Notification",
    "AuditEvent",
    "ChecklistTemplate",
    "Communication",
    "ExtractedField",
    "ReferralPackage",
    "ValidationIssue",
    "ExternalProvider",
    "IdempotencyRecord",
    "IntegrationEvent",
    "Invitation",
    "Organization",
    "PatientReference",
    "PolicyChunk",
    "PolicyDocument",
    "Referral",
    "ReferralDocument",
    "ReferralStatusEvent",
    "Task",
    "User",
]
