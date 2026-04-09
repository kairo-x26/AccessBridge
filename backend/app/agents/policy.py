"""Deterministic policy engine for agent tool use (FR-10, spec §11 agent safety).

The model may *propose*; only this module decides. Inputs it never consults: model
confidence, model-written reasons, document text. Every decision is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from app.agents.tools import REGISTRY, Args, Tool
from app.core.config import get_settings
from app.domain.state_machine import Status

WORKFLOW_TOOLS: dict[str, frozenset[str]] = {
    "intake": frozenset(
        {
            "run_document_analysis",
            "create_coordinator_task",
            "flag_exception",
            "transmit_referral_package",
        }
    ),
    "follow_up": frozenset(
        {"create_coordinator_task", "flag_exception", "send_patient_message", "record_scheduled"}
    ),
    "completion": frozenset(
        {"run_document_analysis", "create_coordinator_task", "propose_completion", "flag_exception"}
    ),
}

Decision = Literal["auto", "approval_required", "denied"]


@dataclass
class PolicyDecision:
    decision: Decision
    reason: str
    tool: Tool | None = None
    args: Args | None = None


@dataclass
class RunBudget:
    tool_calls: int = 0
    external_actions: int = 0


def evaluate(
    *,
    tool_name: str,
    raw_args: dict[str, Any],
    workflow: str,
    referral_status: str,
    budget: RunBudget,
    org_config: dict[str, Any],
) -> PolicyDecision:
    s = get_settings()
    tool = REGISTRY.get(tool_name)
    if tool is None:
        return PolicyDecision("denied", f"Unknown tool {tool_name!r}.")
    if tool_name not in WORKFLOW_TOOLS.get(workflow, frozenset()):
        return PolicyDecision("denied", f"{tool_name} isn't part of the {workflow} workflow.", tool)
    try:
        args = tool.args.model_validate(raw_args)
    except ValidationError as exc:
        return PolicyDecision(
            "denied", f"Arguments failed validation: {exc.error_count()} error(s).", tool
        )
    if Status(referral_status) not in tool.allowed_states:
        return PolicyDecision(
            "denied",
            f"{tool_name} isn't allowed while the referral is {referral_status}.",
            tool,
            args,
        )
    if budget.tool_calls >= s.agent_max_tool_calls:
        return PolicyDecision("denied", "Run reached its tool-call limit.", tool, args)
    if tool.external and budget.external_actions >= s.agent_max_external_actions:
        return PolicyDecision("denied", "Run reached its external-action limit.", tool, args)
    preauthorized = set(org_config.get("preauthorized_tools") or [])
    if tool.always_requires_approval:
        return PolicyDecision(
            "approval_required", "This action always needs staff approval.", tool, args
        )
    if tool_name == "send_patient_message":
        templates = set(org_config.get("preauthorized_templates") or [])
        if tool_name in preauthorized and getattr(args, "template_key", None) in templates:
            return PolicyDecision(
                "auto",
                "Organization pre-authorized this reminder for low-risk follow-up.",
                tool,
                args,
            )
    if tool.external:
        return PolicyDecision(
            "approval_required",
            "External actions need approval unless your organization has "
            "pre-authorized this exact low-risk reminder.",
            tool,
            args,
        )
    return PolicyDecision("auto", "Internal action within the approved workflow.", tool, args)
