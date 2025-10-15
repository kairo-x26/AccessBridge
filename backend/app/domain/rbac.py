"""Role-based access control: the permission matrix (FR-01, spec §3 stakeholders)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"  # clinic administrator
    COORDINATOR = "coordinator"  # referral coordinator
    NAVIGATOR = "navigator"  # patient navigator
    CLINICIAN = "clinician"  # primary care clinician (read-mostly)
    SECURITY = "security"  # IT / security administrator


class Perm(StrEnum):
    REFERRAL_READ = "referral:read"
    REFERRAL_IMPORT = "referral:import"
    REFERRAL_EDIT = "referral:edit"
    REFERRAL_TRANSITION = "referral:transition"
    DOCUMENT_READ = "document:read"
    DOCUMENT_UPLOAD = "document:upload"
    PACKAGE_APPROVE = "package:approve"
    AGENT_RUN = "agent:run"
    ACTION_APPROVE = "action:approve"
    TASK_READ = "task:read"
    TASK_MANAGE = "task:manage"
    MESSAGE_READ = "message:read"
    MESSAGE_SEND = "message:send"
    TEMPLATE_MANAGE = "template:manage"
    OUTCOME_RECORD = "outcome:record"
    POLICY_SEARCH = "policy:search"
    POLICY_MANAGE = "policy:manage"
    REPORT_READ = "report:read"
    REPORT_EXPORT = "report:export"
    CONFIG_MANAGE = "config:manage"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"
    INTEGRATION_MANAGE = "integration:manage"


_STAFF_COMMON = {
    Perm.REFERRAL_READ,
    Perm.DOCUMENT_READ,
    Perm.TASK_READ,
    Perm.MESSAGE_READ,
    Perm.POLICY_SEARCH,
}

MATRIX: dict[Role, frozenset[Perm]] = {
    Role.COORDINATOR: frozenset(
        _STAFF_COMMON
        | {
            Perm.REFERRAL_IMPORT,
            Perm.REFERRAL_EDIT,
            Perm.REFERRAL_TRANSITION,
            Perm.DOCUMENT_UPLOAD,
            Perm.PACKAGE_APPROVE,
            Perm.AGENT_RUN,
            Perm.ACTION_APPROVE,
            Perm.TASK_MANAGE,
            Perm.MESSAGE_SEND,
            Perm.OUTCOME_RECORD,
            Perm.REPORT_READ,
        }
    ),
    Role.NAVIGATOR: frozenset(
        _STAFF_COMMON
        | {
            Perm.TASK_MANAGE,
            Perm.MESSAGE_SEND,
            Perm.ACTION_APPROVE,
            Perm.AGENT_RUN,
            Perm.REFERRAL_TRANSITION,
            Perm.OUTCOME_RECORD,
        }
    ),
    Role.CLINICIAN: frozenset({Perm.REFERRAL_READ, Perm.DOCUMENT_READ, Perm.POLICY_SEARCH}),
    Role.ADMIN: frozenset(set(Perm) - {Perm.INTEGRATION_MANAGE}),
    Role.SECURITY: frozenset(
        {Perm.AUDIT_READ, Perm.USER_MANAGE, Perm.INTEGRATION_MANAGE, Perm.REPORT_READ}
    ),
}


def permissions_for(role: str) -> frozenset[Perm]:
    try:
        return MATRIX[Role(role)]
    except ValueError:
        return frozenset()


def has_permission(role: str, perm: Perm) -> bool:
    return perm in permissions_for(role)
