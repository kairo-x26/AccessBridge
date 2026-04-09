"""Agent orchestrator: plan → policy → act or ask, with a full audit trail (FR-09, FR-10).

The workflow engine (job queue + state machine) owns execution state; the agent only
suggests steps. Every proposal becomes an ``AgentAction`` record whatever the decision, so
denied and pending proposals are as visible as executed ones.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import planner, policy
from app.agents.tools import REGISTRY, ToolContext
from app.ai import gateway
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import DomainError, ValidationFailed
from app.domain.state_machine import Status, allowed_targets
from app.integrations import exchange, sms
from app.models import AgentAction, AgentRun, Approval, Job, Organization, Referral
from app.services import audit, referrals, tasks
from app.workers import queue

WORKFLOW_VERSION = "2026.02"


def _key(referral: Referral, tool: str, args: dict[str, Any]) -> str:
    raw = json.dumps([referral.id, tool, args, referral.version], sort_keys=True, default=str)
    return f"{tool}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def start_run(
    session: Session,
    referral: Referral,
    *,
    workflow: str,
    trigger: str,
    idempotency_key: str | None = None,
) -> tuple[AgentRun, Job]:
    if workflow not in policy.WORKFLOW_TOOLS:
        raise ValidationFailed(f"Unknown workflow {workflow!r}.")
    if idempotency_key:
        prior = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if prior and prior.payload.get("run_id"):
            run = session.get(AgentRun, prior.payload["run_id"])
            if run:
                return run, prior
    run = AgentRun(
        organization_id=referral.organization_id,
        referral_id=referral.id,
        workflow=workflow,
        workflow_version=WORKFLOW_VERSION,
        model_version=gateway.model_version(),
        trigger=trigger,
    )
    session.add(run)
    session.flush()
    job = queue.enqueue(
        session,
        "agent.run",
        {"run_id": run.id, "referral_id": referral.id},
        organization_id=referral.organization_id,
        idempotency_key=idempotency_key or f"run:{run.id}",
    )
    audit.record(
        session,
        organization_id=referral.organization_id,
        actor=trigger,
        operation="agent.run_queued",
        resource_ref=run.id,
        details={"workflow": workflow, "referral_id": referral.id},
    )
    return run, job


def execute_run(session: Session, run: AgentRun) -> dict[str, Any]:
    if run.status in ("completed", "waiting_approval", "failed"):
        return {"status": run.status, "skipped": True}  # redelivered job: already done
    run.status = "running"
    run.started_at = run.started_at or utcnow()
    referral = session.get(Referral, run.referral_id)
    assert referral is not None
    org = session.get(Organization, run.organization_id)
    org_config = org.configuration if org else {}
    budget = policy.RunBudget(tool_calls=run.tool_calls)
    actor = f"agent:{run.id}"
    proposed = executed = 0
    for step in range(get_settings().agent_max_tool_calls):
        state = planner.summarize(session, referral)
        proposals = planner.rules_plan(run.workflow, state)
        if step == 0 and gateway.provider() is not None:
            proposals += planner.llm_plan(session, run.workflow, state, run, run.organization_id)
        acted = False
        for p in proposals:
            key = _key(referral, p.tool, p.args)
            if session.scalar(select(AgentAction.id).where(AgentAction.idempotency_key == key)):
                continue
            d = policy.evaluate(
                tool_name=p.tool,
                raw_args=p.args,
                workflow=run.workflow,
                referral_status=referral.status,
                budget=budget,
                org_config=org_config,
            )
            action = AgentAction(
                organization_id=run.organization_id,
                run_id=run.id,
                referral_id=referral.id,
                tool=p.tool,
                arguments=p.args if d.args is None else d.args.model_dump(),
                reason=p.reason,
                confidence=p.confidence,
                proposed_by=p.proposed_by,
                external=bool(d.tool and d.tool.external),
                decision=d.decision,
                decision_reason=d.reason,
                idempotency_key=key,
                status={
                    "auto": "approved",
                    "approval_required": "pending_approval",
                    "denied": "denied",
                }[d.decision],
            )
            session.add(action)
            session.flush()
            proposed += 1
            audit.record(
                session,
                organization_id=run.organization_id,
                actor=actor,
                operation="agent.propose",
                resource_ref=action.id,
                outcome=d.decision,
                details={"tool": p.tool, "referral_id": referral.id, "proposed_by": p.proposed_by},
            )
            if d.decision == "approval_required":
                _request_approval(session, action, referral, actor)
            elif d.decision == "auto":
                budget.tool_calls += 1
                if action.external:
                    budget.external_actions += 1
                execute_action(session, action, actor=actor, authorized_by="policy:auto", run=run)
                executed += 1
                acted = True
        if not acted:
            break
    run.tool_calls = budget.tool_calls
    pending = session.scalar(
        select(Approval.id)
        .join(AgentAction, AgentAction.id == Approval.action_id)
        .where(AgentAction.run_id == run.id, Approval.decision == "pending")
    )
    run.status = "waiting_approval" if pending else "completed"
    if run.status == "completed":
        run.finished_at = utcnow()
    run.summary = f"{proposed} proposal(s), {executed} executed automatically" + (
        ", waiting for approval" if pending else ""
    )
    audit.record(
        session,
        organization_id=run.organization_id,
        actor=actor,
        operation="agent.run",
        resource_ref=run.id,
        outcome=run.status,
        details={"proposed": proposed, "executed": executed, "model_version": run.model_version},
    )
    return {"status": run.status, "proposed": proposed, "executed": executed}


def _request_approval(
    session: Session, action: AgentAction, referral: Referral, actor: str
) -> Approval:
    tool = REGISTRY[action.tool]
    task, _ = tasks.ensure_task(
        session,
        organization_id=action.organization_id,
        referral_id=referral.id,
        kind="approval",
        title=f"Approve: {tool.description}",
        detail=action.reason,
        owner_id=referral.owner_id,
        created_by=actor,
        priority="high" if tool.external else "normal",
        dedupe_key=f"approval:{action.id}",
    )
    approval = Approval(
        organization_id=action.organization_id,
        action_id=action.id,
        referral_id=referral.id,
        task_id=task.id,
    )
    session.add(approval)
    session.flush()
    return approval


def execute_action(
    session: Session,
    action: AgentAction,
    *,
    actor: str,
    authorized_by: str,
    run: AgentRun | None = None,
) -> AgentAction:
    """Run an authorized action. Re-checks state first: approval can't revive a stale plan."""
    if action.status in ("succeeded", "failed", "skipped", "rejected", "denied"):
        return action
    referral = session.get(Referral, action.referral_id)
    assert referral is not None
    tool = REGISTRY[action.tool]
    if Status(referral.status) not in tool.allowed_states:
        action.status = "skipped"
        action.error = f"Referral is now {referral.status}; action no longer applies."
        audit.record(
            session,
            organization_id=action.organization_id,
            actor=actor,
            operation="agent.action",
            resource_ref=action.id,
            outcome="skipped",
            details={"tool": action.tool, "authorized_by": authorized_by},
        )
        return action
    args = tool.args.model_validate(action.arguments)
    ctx = ToolContext(
        session=session,
        organization_id=action.organization_id,
        referral=referral,
        action=action,
        actor=actor,
        run=run,
    )
    action.authorized_by = authorized_by
    action.status = "executing"
    try:
        with session.begin_nested():
            result = tool.handler(ctx, args)
    except (exchange.TransientSendError, sms.TransientMessagingError) as exc:
        action.status = "approved"  # remains executable; the job layer retries
        action.error = str(exc)
        raise queue.RetryableError(str(exc)) from exc
    except (exchange.PermanentSendError, DomainError) as exc:
        action.status = "failed"
        action.error = str(exc)[:1000]
        audit.record(
            session,
            organization_id=action.organization_id,
            actor=actor,
            operation="agent.action",
            resource_ref=action.id,
            outcome="failed",
            details={
                "tool": action.tool,
                "authorized_by": authorized_by,
                "referral_id": referral.id,
            },
        )
        if tool.external:
            _external_failed(session, referral, actor, str(exc))
        return action
    action.status = "succeeded"
    action.result = result
    action.executed_at = utcnow()
    action.error = None
    audit.record(
        session,
        organization_id=action.organization_id,
        actor=actor,
        operation="agent.action",
        resource_ref=action.id,
        details={
            "tool": action.tool,
            "authorized_by": authorized_by,
            "referral_id": referral.id,
            "result": _safe(result),
        },
    )
    return action


def _safe(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if isinstance(v, str | int | float | bool)}


def _external_failed(session: Session, referral: Referral, actor: str, error: str) -> None:
    """An external action failed: surface it, never report success (spec §5)."""
    if Status.EXCEPTION in allowed_targets(Status(referral.status)):
        referrals.transition(
            session,
            referral,
            Status.EXCEPTION,
            actor=actor,
            reason=f"Transmission failed: {error[:200]}",
        )


def decide(
    session: Session,
    approval: Approval,
    *,
    reviewer_id: str,
    role: str,
    decision: str,
    reason: str | None,
) -> Approval:
    if approval.decision != "pending":
        raise ValidationFailed(f"This approval was already {approval.decision}.")
    action = session.get(AgentAction, approval.action_id)
    assert action is not None
    tool = REGISTRY[action.tool]
    from app.domain.rbac import has_permission

    if not has_permission(role, tool.permission):
        from app.core.errors import Forbidden

        raise Forbidden("Your role can't approve this kind of action.")
    if decision == "rejected" and not (reason and reason.strip()):
        raise ValidationFailed("Give a reason for rejecting this action.")
    approval.decision = decision
    approval.reviewer_id = reviewer_id
    approval.reason = reason
    approval.decided_at = utcnow()
    actor = f"user:{reviewer_id}"
    audit.record(
        session,
        organization_id=approval.organization_id,
        actor=actor,
        operation=f"approval.{decision}",
        resource_ref=approval.id,
        details={"action_id": action.id, "tool": action.tool, "referral_id": action.referral_id},
    )
    if approval.task_id:
        t = session.get(tasks.Task, approval.task_id)
        if t:
            tasks.resolve(session, t, actor=actor, resolution=f"Action {decision}")
    if decision == "approved":
        action.status = "approved"
        queue.enqueue(
            session,
            "agent.execute_action",
            {"action_id": action.id, "approval_id": approval.id, "referral_id": action.referral_id},
            organization_id=approval.organization_id,
            idempotency_key=f"exec:{action.id}",
        )
    else:
        action.status = "rejected"
        action.error = reason
    _maybe_finish_run(session, action.run_id)
    return approval


def _maybe_finish_run(session: Session, run_id: str) -> None:
    run = session.get(AgentRun, run_id)
    if run is None or run.status != "waiting_approval":
        return
    pending = session.scalar(
        select(Approval.id)
        .join(AgentAction, AgentAction.id == Approval.action_id)
        .where(AgentAction.run_id == run_id, Approval.decision == "pending")
    )
    if not pending:
        run.status = "completed"
        run.finished_at = utcnow()


# --- job handlers ---------------------------------------------------------------------


@queue.handler("agent.run")
def _job_run(session: Session, job: Job) -> dict[str, Any]:
    run = session.get(AgentRun, job.payload["run_id"])
    if run is None:
        raise queue.PermanentError("run not found")
    return execute_run(session, run)


@queue.handler("agent.execute_action")
def _job_execute(session: Session, job: Job) -> dict[str, Any]:
    action = session.get(AgentAction, job.payload["action_id"])
    if action is None:
        raise queue.PermanentError("action not found")
    approval = session.get(Approval, job.payload["approval_id"])
    if approval is None or approval.decision != "approved":
        raise queue.PermanentError("action is not approved")
    run = session.get(AgentRun, action.run_id)
    execute_action(
        session,
        action,
        actor=f"agent:{action.run_id}",
        authorized_by=f"approval:{approval.id}:user:{approval.reviewer_id}",
        run=run,
    )
    return {"status": action.status}


@queue.on_dead("agent.execute_action")
def _job_execute_dead(session: Session, job: Job, error: str) -> None:
    action = session.get(AgentAction, job.payload["action_id"])
    if action is None or action.status == "succeeded":
        return
    action.status = "failed"
    action.error = error[:1000]
    referral = session.get(Referral, action.referral_id)
    if referral is not None and REGISTRY[action.tool].external:
        _external_failed(
            session,
            referral,
            f"agent:{action.run_id}",
            "receiving system unavailable after repeated attempts",
        )


@queue.on_dead("agent.run")
def _job_run_dead(session: Session, job: Job, error: str) -> None:
    run = session.get(AgentRun, job.payload["run_id"])
    if run is not None:
        run.status = "failed"
        run.error = error[:1000]
        run.finished_at = utcnow()


@queue.handler("sweep.escalation")
def _job_escalation(session: Session, job: Job) -> dict[str, Any]:
    return {"escalated": len(tasks.escalate_overdue(session))}


@queue.handler("sweep.follow_up")
def _job_follow_up(session: Session, job: Job) -> dict[str, Any]:
    """Workflow B trigger: referrals waiting past the configured threshold."""
    bucket = job.payload.get("bucket", "")
    started = 0
    waiting = (Status.SUBMITTED.value, Status.ACKNOWLEDGED.value, Status.SCHEDULED.value)
    for r in session.scalars(select(Referral).where(Referral.status.in_(waiting))):
        _, created = _start_once(session, r, "follow_up", f"follow-up:{r.id}:{bucket}")
        started += int(created)
    return {"runs_started": started}


def _start_once(session: Session, r: Referral, workflow: str, key: str) -> tuple[AgentRun, bool]:
    exists = session.scalar(select(Job.id).where(Job.idempotency_key == key))
    run, _ = start_run(
        session, r, workflow=workflow, trigger="system:scheduler", idempotency_key=key
    )
    return run, exists is None
