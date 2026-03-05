"""Approved tool registry (spec §10: tool actions pass through permission checks).

Each tool has a typed argument schema, a risk class and the referral states in which it may
run. Arguments carry references only. Handlers are idempotent: they receive the action's
idempotency key and must not repeat external side effects for the same key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.tenancy import get_scoped
from app.domain.rbac import Perm
from app.domain.state_machine import Evidence, Status
from app.integrations import exchange
from app.models import AgentAction, AgentRun, ExternalProvider, Referral, ReferralPackage
from app.services import referrals, tasks, validation

S = Status


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Args):
    pass


class CreateTaskArgs(Args):
    kind: Literal[
        "follow_up",
        "review_package",
        "patient_assistance",
        "missing_info",
        "reconciliation",
        "exception",
    ]
    title_key: Literal[
        "no_acknowledgment",
        "review_package",
        "confirm_appointment",
        "confirm_completion",
        "request_records",
        "patient_needs_help",
        "resolve_exception",
    ]
    priority: Literal["low", "normal", "high"] = "normal"


class TransmitArgs(Args):
    package_id: str = Field(max_length=40)
    provider_id: str = Field(max_length=40)


class FlagExceptionArgs(Args):
    reason_key: Literal[
        "transmission_failed", "no_response", "identity_review", "destination_unavailable"
    ]


TASK_TITLES = {
    "no_acknowledgment": "No acknowledgment from specialist office — follow up",
    "review_package": "Review and approve the referral package",
    "confirm_appointment": "Confirm the appointment was scheduled",
    "confirm_completion": "Confirm the specialist visit happened",
    "request_records": "Request missing records from the referring clinic",
    "patient_needs_help": "Patient asked for help — contact them",
    "resolve_exception": "Resolve referral exception",
}
EXCEPTION_REASONS = {
    "transmission_failed": "Package transmission failed. Check the destination and resend.",
    "no_response": "No response from the specialist office after repeated follow-up.",
    "identity_review": "Patient identity needs review before continuing.",
    "destination_unavailable": "The destination specialist can't accept this referral.",
}


@dataclass
class ToolContext:
    session: Session
    organization_id: str
    referral: Referral
    action: AgentAction
    actor: str
    run: AgentRun | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[Args]
    external: bool
    permission: Perm
    allowed_states: frozenset[Status]
    handler: Callable[[ToolContext, Any], dict[str, Any]]
    always_requires_approval: bool = False


def _create_task(ctx: ToolContext, a: CreateTaskArgs) -> dict[str, Any]:
    task, created = tasks.ensure_task(
        ctx.session,
        organization_id=ctx.organization_id,
        referral_id=ctx.referral.id,
        kind=a.kind,
        title=TASK_TITLES[a.title_key],
        priority=a.priority,
        owner_id=ctx.referral.owner_id,
        created_by=ctx.actor,
        detail=ctx.action.reason,
        dedupe_key=f"agent:{ctx.referral.id}:{a.title_key}",
    )
    return {"task_id": task.id, "created": created}


def _analyze(ctx: ToolContext, _: NoArgs) -> dict[str, Any]:
    from app.ai import extraction, gateway

    assist = (
        extraction.assistant(ctx.session, ctx.organization_id, ctx.run)
        if gateway.provider()
        else None
    )
    s = validation.analyze(ctx.session, ctx.referral, actor=ctx.actor, assist=assist)
    return {
        "documents_processed": s.documents_processed,
        "open_blocking": s.open_blocking,
        "issues": s.issues,
    }


def _transmit(ctx: ToolContext, a: TransmitArgs) -> dict[str, Any]:
    pkg = get_scoped(ctx.session, ReferralPackage, a.package_id, ctx.organization_id)
    prov = get_scoped(ctx.session, ExternalProvider, a.provider_id, ctx.organization_id)
    if pkg.referral_id != ctx.referral.id:
        raise NotFound("Package does not belong to this referral")
    latest = ctx.session.scalar(
        select(ReferralPackage)
        .where(ReferralPackage.referral_id == ctx.referral.id)
        .order_by(ReferralPackage.version.desc())
    )
    if latest is None or latest.id != pkg.id:
        raise exchange.PermanentSendError("Only the latest approved package can be sent")
    if ctx.referral.provider_id != prov.id or not prov.accepts_referrals:
        raise exchange.PermanentSendError("Destination doesn't match the approved referral")
    receipt = exchange.send_package(
        ctx.session, package=pkg, provider=prov, idempotency_key=ctx.action.idempotency_key
    )
    if Status(ctx.referral.status) == S.READY:
        referrals.transition(
            ctx.session,
            ctx.referral,
            S.SUBMITTED,
            actor=ctx.actor,
            evidence_type=Evidence.TRANSMISSION_RECEIPT.value,
            evidence_reference=f"exchange:{receipt.receipt_id}",
        )
    return {
        "receipt_id": receipt.receipt_id,
        "duplicate": receipt.duplicate,
        "external_message_sent": not receipt.duplicate,
    }


def _flag_exception(ctx: ToolContext, a: FlagExceptionArgs) -> dict[str, Any]:
    ev = referrals.transition(
        ctx.session,
        ctx.referral,
        S.EXCEPTION,
        actor=ctx.actor,
        reason=EXCEPTION_REASONS[a.reason_key],
    )
    return {"event_id": ev.id}


OPEN = frozenset(set(Status) - {S.COMPLETED, S.DECLINED, S.CANCELLED})

REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "run_document_analysis",
            "Extract and validate referral documents.",
            NoArgs,
            external=False,
            permission=Perm.REFERRAL_EDIT,
            allowed_states=frozenset({S.NEEDS_REVIEW, S.EXCEPTION}),
            handler=_analyze,
        ),
        Tool(
            "create_coordinator_task",
            "Create a staff task from an approved title.",
            CreateTaskArgs,
            external=False,
            permission=Perm.TASK_MANAGE,
            allowed_states=OPEN,
            handler=_create_task,
        ),
        Tool(
            "flag_exception",
            "Move the referral to an operational exception.",
            FlagExceptionArgs,
            external=False,
            permission=Perm.REFERRAL_TRANSITION,
            allowed_states=frozenset(
                {S.NEEDS_REVIEW, S.READY, S.SUBMITTED, S.ACKNOWLEDGED, S.SCHEDULED}
            ),
            handler=_flag_exception,
            always_requires_approval=True,
        ),
        Tool(
            "transmit_referral_package",
            "Send the approved package to the specialist.",
            TransmitArgs,
            external=True,
            permission=Perm.ACTION_APPROVE,
            allowed_states=frozenset({S.READY}),
            handler=_transmit,
            always_requires_approval=True,
        ),
    ]
}


def register(tool: Tool) -> None:
    REGISTRY[tool.name] = tool
