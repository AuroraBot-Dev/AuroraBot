from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from src.ai.contracts import (
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelResult,
    ModelUsage,
    ToolCall,
)
from src.ai.vnext import ModelCapabilityError, ModelGatewayService
from src.kernel.contracts import TaskStatus
from src.localhost.configuration import load_configuration
from src.localhost.runtime import AuroraRuntime
from tests.test_events import valid_amp

if TYPE_CHECKING:
    from pathlib import Path


def test_gateway_negotiates_declared_role_capabilities(project_root: Path) -> None:
    service = ModelGatewayService(load_configuration(project_root))
    request = ModelRequest(role="fast", messages=(ModelMessage("user", "test"),), output_schema={"type": "object"})
    assert {"chat", "structured_output"} <= service.negotiate(request)
    with pytest.raises(ModelCapabilityError, match="native"):
        service.negotiate(ModelRequest(role="fast", messages=(), response_mode="native"))


def test_json_text_fallback_normalizes_valid_json(project_root: Path) -> None:
    service = ModelGatewayService(load_configuration(project_root))
    request = ModelRequest(role="fast", messages=(), output_schema={"type": "object", "required": ["kind"]})
    data, diagnostics = service._normalize_output('{"kind":"no_action"}', request, frozenset({"json_text_fallback"}))
    assert data == {"kind": "no_action"}
    assert diagnostics == ("output mode: json_text_fallback",)


def test_invalid_model_json_returns_configured_no_action(project_root: Path) -> None:
    service = ModelGatewayService(load_configuration(project_root))
    request = ModelRequest(
        role="fast",
        messages=(),
        output_schema={"type": "object", "required": ["kind"]},
        invalid_output_result={"kind": "no_action"},
    )
    data, diagnostics = service._normalize_output("not JSON", request, frozenset({"json_text_fallback"}))
    assert data == {"kind": "no_action"}
    assert "no_action" in diagnostics[-1]


def test_model_call_without_credential_is_rejected_before_provider_request(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        monkeypatch.delenv("AURORA_TEST_MODEL_API_KEY", raising=False)
        service = ModelGatewayService(load_configuration(project_root))
        with pytest.raises(ModelGatewayError, match="missing model credential"):
            await service.complete(ModelRequest(role="fast", messages=(ModelMessage("user", "test"),)))

    asyncio.run(scenario())


class _ToolGateway:
    def __init__(self, arguments: dict[str, object]) -> None:
        self.arguments = arguments
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResult:
        self.requests.append(request)
        return ModelResult(
            model="fake",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode=request.response_mode,
            text="",
            data=None,
            usage=ModelUsage(),
            cost_usd=0,
            tool_calls=(ToolCall("call", "org.aurora.console.send_message", self.arguments),),
            finish_reason="tool_calls",
        )


def test_model_activity_runs_outside_kernel_and_creates_auditable_effect(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        gateway = _ToolGateway({"text": "model hello"})
        runtime.model_gateway = gateway
        await runtime.submit_amp(valid_amp())
        first = await runtime.pump()
        assert runtime._model_dispatch_task is not None
        await runtime._model_dispatch_task
        second = await runtime.pump()
        third = await runtime.pump()
        task_id = first["ingested_task_ids"][0]
        detail = runtime.task(task_id)
        assert detail is not None
        assert any(event["type"] == "model.completed" for event in detail["events"])
        assert any(event["type"] == "agent.effect" for event in detail["events"])
        assert second["platform_receipts_emitted"] == 1
        assert third["ingested_task_ids"]
        assert runtime.kernel.get_task(task_id).status == TaskStatus.COMPLETED  # type: ignore[union-attr]
        await runtime.shutdown()

    asyncio.run(scenario())


def test_invalid_effect_arguments_fail_agent_without_platform_call(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        runtime.model_gateway = _ToolGateway({"text": 1})
        await runtime.submit_amp(valid_amp())
        await runtime.pump()
        assert runtime._model_dispatch_task is not None
        await runtime._model_dispatch_task
        result = await runtime.pump()
        assert result["failed_message_ids"]
        assert result["platform_receipts_emitted"] == 0
        await runtime.shutdown()

    asyncio.run(scenario())
