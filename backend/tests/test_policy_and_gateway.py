from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents import policy
from app.ai import gateway
from app.ai.extraction import ExtractionOut


def _eval(tool, args, status="needs_review", workflow="intake", budget=None, cfg=None):
    return policy.evaluate(
        tool_name=tool,
        raw_args=args,
        workflow=workflow,
        referral_status=status,
        budget=budget or policy.RunBudget(),
        org_config=cfg or {},
    )


def test_out_of_workflow_tool_denied():
    d = _eval(
        "create_coordinator_task",
        {"kind": "follow_up", "title_key": "review_package"},
        workflow="completion_x",
    )
    assert d.decision == "denied"


def test_transmit_needs_ready_state_and_approval():
    args = {"package_id": "pkg_1", "provider_id": "prv_1"}
    assert _eval("transmit_referral_package", args).decision == "denied"
    d = _eval("transmit_referral_package", args, status="ready")
    assert d.decision == "approval_required"
    d = _eval(
        "transmit_referral_package",
        args,
        status="ready",
        cfg={"preauthorized_tools": ["transmit_referral_package"]},
    )
    assert d.decision == "approval_required"


def test_budgets_cap_tool_calls_and_external_actions():
    args = {"package_id": "pkg_1", "provider_id": "prv_1"}
    d = _eval(
        "transmit_referral_package",
        args,
        status="ready",
        budget=policy.RunBudget(external_actions=1),
    )
    assert d.decision == "denied" and "external-action" in d.reason
    d = _eval("run_document_analysis", {}, budget=policy.RunBudget(tool_calls=99))
    assert d.decision == "denied"


def test_confidence_is_not_an_input():
    import inspect

    assert "confidence" not in inspect.signature(policy.evaluate).parameters


def test_flag_exception_always_needs_approval():
    d = _eval("flag_exception", {"reason_key": "no_response"}, status="submitted")
    assert d.decision == "approval_required"


# --- Anthropic provider, exercised with a stub client (no network) ----------------------


class _Stub:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.kwargs = response, exc, None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def _provider(stub):
    pytest.importorskip("anthropic")
    p = gateway.AnthropicProvider("claude-opus-5-5", "medium", api_key="test")
    p.client = stub
    return p


def _resp(text, stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop,
        model="claude-opus-5-5",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def test_anthropic_provider_parses_schema_output():
    stub = _Stub(_resp('{"fields": [{"name": "mrn", "quote": "123456"}]}'))
    out = _provider(stub).complete_json(system="s", user="u", schema=ExtractionOut, max_tokens=100)
    assert out.data.fields[0].quote == "123456"
    assert stub.kwargs["model"] == "claude-opus-5-5"
    assert stub.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert stub.kwargs["fallbacks"] == "default"
    assert "thinking" not in stub.kwargs


@pytest.mark.parametrize(
    "resp",
    [
        _resp("{}", stop="refusal"),
        _resp('{"f', stop="max_tokens"),
        _resp("not json"),
        _resp('{"fields": [{"name": "x"}]}'),
    ],
)
def test_anthropic_provider_failures_become_unavailable(resp):
    with pytest.raises(gateway.LLMUnavailable):
        _provider(_Stub(resp)).complete_json(
            system="s", user="u", schema=ExtractionOut, max_tokens=100
        )


def test_strict_schema_closes_objects():
    schema = gateway.strict_schema(ExtractionOut)
    assert schema["additionalProperties"] is False
    item = schema["$defs"]["ExtractedQuote"]
    assert item["additionalProperties"] is False and set(item["required"]) == {"name", "quote"}


def test_no_provider_means_rules_only():
    gateway.set_provider(None)
    assert gateway.model_version() == "rules-v1"
