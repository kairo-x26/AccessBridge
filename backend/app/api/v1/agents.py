"""Agent runs, approvals and background job operations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.agents import orchestrator
from app.api.deps import DB, Principal, require
from app.core.errors import ValidationFailed
from app.core.tenancy import get_scoped, scoped
from app.domain.rbac import Perm
from app.models import AgentAction, AgentRun, Approval, Job, Referral
from app.services import audit
from app.workers import queue

router = APIRouter(tags=["agents"])
Runner = Annotated[Principal, Depends(require(Perm.AGENT_RUN))]
Reader = Annotated[Principal, Depends(require(Perm.REFERRAL_READ))]
Approver = Annotated[Principal, Depends(require(Perm.ACTION_APPROVE))]
Ops = Annotated[Principal, Depends(require(Perm.CONFIG_MANAGE))]


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    referral_id: str
    tool: str
    arguments: dict[str, Any]
    reason: str
    confidence: float | None
    proposed_by: str
    external: bool
    decision: str
    decision_reason: str | None
    status: str
    result: dict[str, Any] | None
    error: str | None
    authorized_by: str | None
    executed_at: datetime | None
    created_at: datetime


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    referral_id: str
    decision: str
    reviewer_id: str | None
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    referral_id: str
    workflow: str
    workflow_version: str
    model_version: str
    trigger: str
    status: str
    summary: str | None
    error: str | None
    input_tokens: int
    output_tokens: int
    tool_calls: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetail(RunOut):
    actions: list[ActionOut]
    approvals: list[ApprovalOut]


class AnalyzeOut(BaseModel):
    run_id: str
    job_id: str
    status: str


class AnalyzeIn(BaseModel):
    workflow: Literal["intake", "follow_up", "completion"] = "intake"


@router.post("/referrals/{referral_id}/analyze", response_model=AnalyzeOut, status_code=202)
def analyze(
    referral_id: str, principal: Runner, session: DB, body: AnalyzeIn | None = None
) -> AnalyzeOut:
    """Queue validation, extraction and agent planning (spec §9)."""
    r = get_scoped(session, Referral, referral_id, principal.organization_id)
    run, job = orchestrator.start_run(
        session, r, workflow=(body or AnalyzeIn()).workflow, trigger=principal.actor
    )
    return AnalyzeOut(run_id=run.id, job_id=job.id, status=run.status)


@router.get("/referrals/{referral_id}/agent-runs", response_model=list[RunOut])
def runs_for_referral(referral_id: str, principal: Reader, session: DB) -> list[AgentRun]:
    get_scoped(session, Referral, referral_id, principal.organization_id)
    return list(
        session.scalars(
            select(AgentRun)
            .where(AgentRun.referral_id == referral_id)
            .order_by(AgentRun.created_at.desc())
        )
    )


def _detail(session: DB, run: AgentRun) -> RunDetail:
    actions = session.scalars(
        select(AgentAction).where(AgentAction.run_id == run.id).order_by(AgentAction.created_at)
    ).all()
    approvals = session.scalars(
        select(Approval).where(Approval.action_id.in_([a.id for a in actions]))
    ).all()
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        actions=[ActionOut.model_validate(a) for a in actions],
        approvals=[ApprovalOut.model_validate(a) for a in approvals],
    )


@router.get("/agent-runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, principal: Reader, session: DB) -> RunDetail:
    """Inspect execution progress and decisions (spec §9)."""
    return _detail(session, get_scoped(session, AgentRun, run_id, principal.organization_id))


class PendingApproval(ApprovalOut):
    action: ActionOut
    patient_name: str
    referral_status: str
    specialty: str


@router.get("/approvals", response_model=list[PendingApproval])
def list_approvals(
    principal: Reader,
    session: DB,
    status: Literal["pending", "approved", "rejected"] = "pending",
    limit: int = Query(100, le=500),
) -> list[PendingApproval]:
    rows = session.scalars(
        scoped(Approval, principal.organization_id)
        .where(Approval.decision == status)
        .order_by(Approval.created_at)
        .limit(limit)
    ).all()
    out = []
    for a in rows:
        action = session.get(AgentAction, a.action_id)
        ref = session.get(Referral, a.referral_id)
        assert action is not None and ref is not None
        out.append(
            PendingApproval(
                **ApprovalOut.model_validate(a).model_dump(),
                action=ActionOut.model_validate(action),
                patient_name=ref.patient.display_name,
                referral_status=ref.status,
                specialty=ref.specialty,
            )
        )
    return out


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=500)


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
def decide(approval_id: str, body: DecisionIn, principal: Approver, session: DB) -> Approval:
    """Approve or reject a pending agent action (spec §9)."""
    approval = get_scoped(session, Approval, approval_id, principal.organization_id)
    return orchestrator.decide(
        session,
        approval,
        reviewer_id=principal.user_id,
        role=principal.role,
        decision=body.decision,
        reason=body.reason,
    )


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    run_after: datetime
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None
    payload: dict[str, Any]


@router.get("/ops/jobs", response_model=list[JobOut])
def list_jobs(
    principal: Ops,
    session: DB,
    status: Literal["queued", "running", "succeeded", "dead"] | None = None,
    limit: int = Query(100, le=500),
) -> list[Job]:
    q = scoped(Job, principal.organization_id)
    if status:
        q = q.where(Job.status == status)
    return list(session.scalars(q.order_by(Job.created_at.desc()).limit(limit)))


@router.post("/ops/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, principal: Ops, session: DB) -> Job:
    job = get_scoped(session, Job, job_id, principal.organization_id)
    if job.status != "dead":
        raise ValidationFailed("Only failed (dead-lettered) jobs can be retried.")
    queue.retry_dead(session, job)
    audit.record(
        session,
        organization_id=principal.organization_id,
        actor=principal.actor,
        operation="job.retry",
        resource_ref=job.id,
    )
    return job
