from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id, utcnow


class Job(Base):
    """Durable unit of background work: at-least-once, leased, retried, dead-lettered."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "run_after"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    organization_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    run_after: Mapped[datetime] = mapped_column(default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(String(1000))
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    workflow: Mapped[str] = mapped_column(String(40))  # intake | follow_up | completion
    workflow_version: Mapped[str] = mapped_column(String(20))
    model_version: Mapped[str] = mapped_column(String(80))
    trigger: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(1000))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    tool_calls: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class AgentAction(TimestampMixin, Base):
    __tablename__ = "agent_actions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("act"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    # Arguments hold references (ids, template keys), never free-text PHI.
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(500))
    confidence: Mapped[float | None]
    proposed_by: Mapped[str] = mapped_column(String(40))  # rules | llm
    external: Mapped[bool] = mapped_column(default=False)
    decision: Mapped[str] = mapped_column(String(30))  # auto | approval_required | denied
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(1000))
    authorized_by: Mapped[str | None] = mapped_column(String(80))
    executed_at: Mapped[datetime | None]


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("apr"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("agent_actions.id"), unique=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(String(500))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    decided_at: Mapped[datetime | None]


class LLMUsage(Base):
    """Metered model usage per call, for cost-per-workflow reporting (NFR cost)."""

    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("llm"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"))
    task: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    outcome: Mapped[str] = mapped_column(String(30))  # ok | refused | invalid | error
    request_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExchangeTransmission(Base):
    """Outbound referral package transmissions; one row per idempotency key."""

    __tablename__ = "exchange_transmissions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("xmt"))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    referral_id: Mapped[str] = mapped_column(ForeignKey("referrals.id"), index=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("referral_packages.id"))
    provider_id: Mapped[str] = mapped_column(ForeignKey("external_providers.id"))
    status: Mapped[str] = mapped_column(String(20))  # sent | failed
    receipt_id: Mapped[str | None] = mapped_column(String(120))
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None]
