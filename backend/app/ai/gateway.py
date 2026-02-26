"""LLM gateway: one place for provider choice, privacy controls, caps and metering.

Providers return JSON validated against a Pydantic schema. Nothing a provider returns is
trusted: callers still ground values in source text and pass proposals through the policy
engine. The default ``deterministic`` provider makes no model calls at all; the platform is
fully functional without one, and model assistance is an opt-in per deployment (it requires
an appropriate business associate agreement before any PHI is sent).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import redact
from app.models import AgentRun, LLMUsage

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """No model provider is configured, or the call failed; callers fall back to rules."""


class BudgetExceeded(LLMUnavailable):
    pass


@dataclass
class LLMResponse:
    data: BaseModel
    input_tokens: int
    output_tokens: int
    model: str
    request_id: str | None = None


class Provider(Protocol):
    name: str
    model: str

    def complete_json(
        self, *, system: str, user: str, schema: type[BaseModel], max_tokens: int
    ) -> LLMResponse: ...


class AnthropicProvider:
    """Calls Claude through the official SDK with a JSON-schema constrained output."""

    name = "anthropic"

    def __init__(self, model: str, effort: str, api_key: str | None = None) -> None:
        import anthropic

        self.model = model
        self.effort = effort
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def complete_json(
        self, *, system: str, user: str, schema: type[BaseModel], max_tokens: int
    ) -> LLMResponse:
        from anthropic.types.beta import BetaOutputConfigParam, BetaUserMessageParam

        a = self._anthropic
        message: BetaUserMessageParam = {"role": "user", "content": user}
        output_config: BetaOutputConfigParam = {
            "effort": self.effort,  # type: ignore[typeddict-item]
            "format": {"type": "json_schema", "schema": strict_schema(schema)},
        }
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[message],
                output_config=output_config,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.RateLimitError as exc:
            raise LLMUnavailable("model rate limited") from exc
        except a.APIStatusError as exc:
            raise LLMUnavailable(f"model API error {exc.status_code}") from exc
        except a.APIConnectionError as exc:
            raise LLMUnavailable("model API unreachable") from exc
        if response.stop_reason == "refusal":
            raise LLMUnavailable("model declined the request")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailable("model output was truncated")
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            data = schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMUnavailable("model output failed schema validation") from exc
        return LLMResponse(
            data=data,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            request_id=getattr(response, "_request_id", None),
        )


def strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema with ``additionalProperties: false`` on every object."""
    raw = schema.model_json_schema()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
                node["required"] = list((node.get("properties") or {}).keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(raw)
    return raw


_provider_override: Provider | None = None


def set_provider(provider: Provider | None) -> None:
    """Install a provider explicitly (tests, evaluation runs)."""
    global _provider_override
    _provider_override = provider


def provider() -> Provider | None:
    if _provider_override is not None:
        return _provider_override
    s = get_settings()
    if s.llm_provider == "anthropic":
        return AnthropicProvider(s.llm_model, s.llm_effort, s.anthropic_api_key)
    return None


def model_version() -> str:
    p = provider()
    return f"{p.name}:{p.model}" if p else "rules-v1"


def complete(
    session: Session,
    *,
    organization_id: str,
    task: str,
    system: str,
    user: str,
    schema: type[BaseModel],
    run: AgentRun | None = None,
    max_tokens: int = 4000,
    redact_contacts: bool = True,
) -> LLMResponse:
    p = provider()
    if p is None:
        raise LLMUnavailable("no model provider configured")
    s = get_settings()
    if run is not None and run.input_tokens + run.output_tokens >= s.llm_max_tokens_per_run:
        raise BudgetExceeded("run token budget exhausted")
    # Minimize PHI: contact details are never needed for administrative reasoning.
    prompt = redact(user) if redact_contacts else user
    try:
        out = p.complete_json(system=system, user=prompt, schema=schema, max_tokens=max_tokens)
        outcome = "ok"
    except LLMUnavailable as exc:
        session.add(
            LLMUsage(
                organization_id=organization_id,
                run_id=run.id if run else None,
                task=task,
                provider=p.name,
                model=p.model,
                outcome="error",
            )
        )
        log.warning("llm call failed", extra={"fields": {"task": task, "error": str(exc)}})
        raise
    session.add(
        LLMUsage(
            organization_id=organization_id,
            run_id=run.id if run else None,
            task=task,
            provider=p.name,
            model=out.model,
            input_tokens=out.input_tokens,
            output_tokens=out.output_tokens,
            outcome=outcome,
            request_id=out.request_id,
        )
    )
    if run is not None:
        run.input_tokens += out.input_tokens
        run.output_tokens += out.output_tokens
    return out
