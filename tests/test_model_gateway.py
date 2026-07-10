from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.ai.contracts import ModelGatewayError, ModelMessage, ModelRequest, ModelResult, ModelUsage
from src.ai.vnext import ModelCapabilityError, ModelGatewayService
from src.localhost.configuration import load_configuration
from src.localhost.runtime import AuroraRuntime
from tests.test_events import valid_amp

if TYPE_CHECKING:
    from pathlib import Path


def test_gateway_negotiates_declared_role_capabilities(project_root: Path) -> None:
    service = ModelGatewayService(load_configuration(project_root))
    request = ModelRequest(role="fast", messages=(ModelMessage("user", "test"),), output_schema={"type": "object"})

    negotiated = service.negotiate(request)

    assert {"chat", "structured_output"} <= negotiated
    with pytest.raises(ModelCapabilityError, match="native"):
        service.negotiate(ModelRequest(role="fast", messages=(), response_mode="native"))


def test_json_text_fallback_normalizes_valid_json(project_root: Path) -> None:
    service = ModelGatewayService(load_configuration(project_root))
    request = ModelRequest(
        role="fast",
        messages=(),
        output_schema={"type": "object", "required": ["kind"]},
    )

    data, diagnostics = service._normalize_output('{"kind":"no_action"}', request, frozenset({"json_text_fallback"}))

    assert data == {"kind": "no_action"}
    assert diagnostics == ("output mode: json_text_fallback",)


def test_invalid_model_json_returns_configured_no_action(project_root: Path) -> None:
    service = ModelGatewayService(load_configuration(project_root))
    request = ModelRequest(
        role="fast",
        messages=(),
        output_schema={
            "type": "object",
            "properties": {"kind": {"const": "no_action"}, "summary": {"type": "string"}},
            "required": ["kind", "summary"],
        },
        invalid_output_result={"kind": "no_action", "summary": "invalid output"},
    )

    data, diagnostics = service._normalize_output("not JSON", request, frozenset({"json_text_fallback"}))

    assert data == {"kind": "no_action", "summary": "invalid output"}
    assert "no_action" in diagnostics[-1]


def test_model_call_without_credential_is_rejected_before_provider_request(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        service = ModelGatewayService(load_configuration(project_root))
        request = ModelRequest(role="fast", messages=(ModelMessage("user", "test"),))
        with pytest.raises(ModelGatewayError, match="missing model credential"):
            await service.complete(request)

    asyncio.run(scenario())


class _FakeModelGateway:
    def __init__(self, decision: dict[str, object] | None) -> None:
        self.decision = decision

    async def complete(self, _request: ModelRequest) -> ModelResult:
        return ModelResult(
            model="openai/fake",
            negotiated_capabilities=frozenset({"chat", "structured_output"}),
            response_mode="normalized",
            text="{}",
            data=self.decision,
            usage=ModelUsage(),
            cost_usd=0.0,
        )


def _enable_model_decide(project_root: Path) -> None:
    nodes = project_root / "config" / "nodes.toml"
    content = nodes.read_text(encoding="utf-8")
    content = content.replace('id = "builtin.decide"\nenabled = true', 'id = "builtin.decide"\nenabled = false')
    content = content.replace(
        'id = "builtin.model_decide"\nenabled = false', 'id = "builtin.model_decide"\nenabled = true'
    )
    content = content.replace('[[edge]]\nevent_type = "message.received"\ntarget = "builtin.decide"\n', "")
    content += '\n[[edge]]\nevent_type = "message.received"\ntarget = "builtin.model_decide"\n'
    nodes.write_text(content, encoding="utf-8")


def test_model_decide_creates_auditable_model_chain_and_valid_effect(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_model_decide(project_root)
        runtime = AuroraRuntime.create(project_root)
        runtime.kernel._model_gateway = _FakeModelGateway(
            {"kind": "effect", "capability": "debug.echo", "parameters": {"text": "model hello"}, "summary": "echo"}
        )
        await runtime.submit_amp(valid_amp())

        result = await runtime.run_cycle()

        assert result["platform_receipts_emitted"] == 1
        records = runtime.kernel._records()
        requested = next(record for record in records if record.amp["payload"]["type"] == "model.requested")
        completed = next(record for record in records if record.amp["payload"]["type"] == "model.completed")
        effect = next(record for record in records if record.amp["payload"]["type"] == "effect.requested")
        assert completed.parent_record_id == requested.record_id
        assert effect.amp["payload"]["data"]["parameters"] == {"text": "model hello"}

    asyncio.run(scenario())


def test_model_decide_accepts_action_invoke_compatibility_shape(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_model_decide(project_root)
        runtime = AuroraRuntime.create(project_root)
        runtime.kernel._model_gateway = _FakeModelGateway(
            {"action": "invoke", "capability": "debug.echo", "parameters": {"text": "legacy shape"}}
        )
        await runtime.submit_amp(valid_amp())
        await runtime.run_cycle()

        effect = next(
            record for record in runtime.kernel._records() if record.amp["payload"]["type"] == "effect.requested"
        )
        assert effect.amp["payload"]["data"]["parameters"] == {"text": "legacy shape"}

    asyncio.run(scenario())


def test_invalid_model_effect_parameters_do_not_create_effect(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_model_decide(project_root)
        runtime = AuroraRuntime.create(project_root)
        runtime.kernel._model_gateway = _FakeModelGateway(
            {"kind": "effect", "capability": "debug.echo", "parameters": {"text": 1}, "summary": "invalid"}
        )
        await runtime.submit_amp(valid_amp())
        await runtime.run_cycle()

        effects = [
            record for record in runtime.kernel._records() if record.amp["payload"]["type"] == "effect.requested"
        ]
        assert not effects

    asyncio.run(scenario())
