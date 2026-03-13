"""Referral Workflow Agent planning (spec §11).

Rules produce the baseline plan from structured state. When a model is configured it may add
proposals from a PHI-free state summary — it never sees documents or patient details — and
those proposals go through the same policy engine as everything else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.policy import WORKFLOW_TOOLS
from app.agents.tools import REGISTRY
from app.ai import gateway
from app.core.config import get_settings
from app.core.db import utcnow
from app.domain.state_machine import Status
from app.models import (
    AgentRun,
    ReferralDocument,
    ReferralPackage,
    Task,
    ValidationIssue,
)
from app.models.referral import Referral
from app.services.tasks import OPEN_STATES

S = Status


@dataclass
class Proposal:
    tool: str
    args: dict[str, Any]
    reason: str
    confidence: float | None = None
    proposed_by: str = "rules"
    extra: dict[str, Any] = field(default_factory=dict)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


@dataclass
class StateSummary:
    """Everything the planner may know. Identifiers and counts only — no PHI."""

    referral_id: str
    status: str
    specialty: str
    days_in_status: int
    pending_documents: int
    open_blocking_issues: int
    unreviewed_critical_fields: int
    latest_package_id: str | None
    provider_id: str | None
    provider_accepting: bool
    appointment_passed: bool
    open_task_titles: list[str]
    resolved_follow_ups: int

    def to_prompt(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True)


def summarize(session: Session, r: Referral) -> StateSummary:
    from app.models import ExtractedField

    now = utcnow()
    changed = _aware(r.status_changed_at) or now
    pkg = session.scalar(
        select(ReferralPackage)
        .where(ReferralPackage.referral_id == r.id)
        .order_by(ReferralPackage.version.desc())
    )
    appt = _aware(r.appointment_at)
    return StateSummary(
        referral_id=r.id,
        status=r.status,
        specialty=r.specialty,
        days_in_status=(now - changed).days,
        pending_documents=session.scalar(
            select(func.count()).where(
                ReferralDocument.referral_id == r.id,
                ReferralDocument.extraction_status == "pending",
            )
        )
        or 0,
        open_blocking_issues=session.scalar(
            select(func.count()).where(
                ValidationIssue.referral_id == r.id,
                ValidationIssue.status == "open",
                ValidationIssue.severity == "blocking",
            )
        )
        or 0,
        unreviewed_critical_fields=session.scalar(
            select(func.count()).where(
                ExtractedField.referral_id == r.id,
                ExtractedField.critical.is_(True),
                ExtractedField.status == "candidate",
            )
        )
        or 0,
        latest_package_id=pkg.id if pkg else None,
        provider_id=r.provider_id,
        provider_accepting=bool(r.provider and r.provider.accepts_referrals),
        appointment_passed=bool(appt and appt + timedelta(days=1) < now),
        open_task_titles=list(
            session.scalars(
                select(Task.title).where(Task.referral_id == r.id, Task.status.in_(OPEN_STATES))
            )
        ),
        resolved_follow_ups=session.scalar(
            select(func.count()).where(
                Task.referral_id == r.id, Task.kind == "follow_up", Task.status.not_in(OPEN_STATES)
            )
        )
        or 0,
    )


def rules_plan(workflow: str, st: StateSummary) -> list[Proposal]:
    threshold = get_settings().follow_up_after_days
    status = Status(st.status)
    out: list[Proposal] = []
    if workflow == "intake":
        if status in (S.NEEDS_REVIEW, S.EXCEPTION) and st.pending_documents:
            out.append(
                Proposal(
                    "run_document_analysis",
                    {},
                    f"{st.pending_documents} document(s) not yet analyzed.",
                    0.99,
                )
            )
        elif status == S.NEEDS_REVIEW and not st.open_blocking_issues and not st.pending_documents:
            out.append(
                Proposal(
                    "create_coordinator_task",
                    {"kind": "review_package", "title_key": "review_package"},
                    "Checklist complete; package is ready for coordinator review.",
                    0.95,
                )
            )
        if status == S.READY and st.latest_package_id and st.provider_id:
            if st.provider_accepting:
                out.append(
                    Proposal(
                        "transmit_referral_package",
                        {"package_id": st.latest_package_id, "provider_id": st.provider_id},
                        "Package approved and destination accepts referrals.",
                        0.97,
                    )
                )
            else:
                out.append(
                    Proposal(
                        "flag_exception",
                        {"reason_key": "destination_unavailable"},
                        "Approved destination is no longer accepting referrals.",
                        0.9,
                    )
                )
    elif workflow == "follow_up":
        if status == S.SUBMITTED and st.days_in_status >= threshold:
            if st.resolved_follow_ups >= 2 and st.days_in_status >= 3 * threshold:
                out.append(
                    Proposal(
                        "flag_exception",
                        {"reason_key": "no_response"},
                        "Repeated follow-ups produced no acknowledgment.",
                        0.85,
                    )
                )
            else:
                out.append(
                    Proposal(
                        "create_coordinator_task",
                        {"kind": "follow_up", "title_key": "no_acknowledgment"},
                        "No acknowledgment recorded",
                        0.94,
                    )
                )
        if status == S.ACKNOWLEDGED and st.days_in_status >= threshold:
            out.append(
                Proposal(
                    "create_coordinator_task",
                    {"kind": "follow_up", "title_key": "confirm_appointment"},
                    "Acknowledged but no appointment recorded.",
                    0.9,
                )
            )
        if status == S.SCHEDULED and st.appointment_passed:
            out.append(
                Proposal(
                    "create_coordinator_task",
                    {"kind": "follow_up", "title_key": "confirm_completion"},
                    "Appointment date has passed without completion evidence.",
                    0.9,
                )
            )
    return out


class LLMProposal(BaseModel):
    tool: str = Field(max_length=60)
    arguments_json: str = Field(max_length=2000)
    reason: str = Field(max_length=300)


class LLMPlan(BaseModel):
    proposals: list[LLMProposal] = Field(max_length=5)


PLANNER_SYSTEM = """You help coordinate administrative steps for outpatient specialist \
referrals. You never make clinical decisions, set urgency, or contact anyone directly.

Given a referral's workflow state (identifiers and counts only) and the tools available, \
propose at most three next administrative steps that the state supports. Use only the listed \
tools and arguments; arguments_json must be a JSON object matching the tool's schema. If \
nothing is needed, return no proposals. Every proposal is reviewed by a policy engine and, \
for external actions, by staff."""


def llm_plan(
    session: Session, workflow: str, st: StateSummary, run: AgentRun, organization_id: str
) -> list[Proposal]:
    tools = [
        {
            "name": n,
            "description": REGISTRY[n].description,
            "arguments_schema": REGISTRY[n].args.model_json_schema(),
        }
        for n in sorted(WORKFLOW_TOOLS.get(workflow, frozenset()))
        if n in REGISTRY
    ]
    try:
        out = gateway.complete(
            session,
            organization_id=organization_id,
            task=f"plan_{workflow}",
            system=PLANNER_SYSTEM,
            user=f"Workflow: {workflow}\nState: {st.to_prompt()}\nTools: {json.dumps(tools)}",
            schema=LLMPlan,
            run=run,
            max_tokens=2000,
        )
    except gateway.LLMUnavailable:
        return []
    assert isinstance(out.data, LLMPlan)
    proposals = []
    for p in out.data.proposals[:3]:
        try:
            args = json.loads(p.arguments_json)
        except json.JSONDecodeError:
            args = {"__invalid__": p.arguments_json[:100]}
        if not isinstance(args, dict):
            args = {"__invalid__": True}
        proposals.append(Proposal(p.tool, args, p.reason[:300], None, "llm"))
    return proposals
