from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from src.ai.gateway import GatewayError
from src.ai.vnext import ModelCapabilityError, ModelGatewayService
from src.contracts.agent import TaskStatus
from src.contracts.configuration import load_configuration
from src.contracts.model import (
    ModelBudget,
    ModelBudgetError,
    ModelContinuation,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelResult,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)
from src.localhost.ports import EffectExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.console import CONSOLE_SEND_DESCRIPTOR, ConsolePlatform
from tests.test_events import valid_amp

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_CHAT_COST = 0.125
_NATIVE_COST = 0.25
_EXPECTED_FALLBACK_CALLS = 2


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


@pytest.mark.parametrize(
    ("model_request", "message"),
    (
        (ModelRequest(role="missing", messages=()), "unknown model role"),
        (ModelRequest(role="fast", messages=(), retry_policy="retry"), "retry_policy"),  # type: ignore[arg-type]
        (ModelRequest(role="fast", messages=(), parallel_tool_calls=True), "parallel tool"),
        (ModelRequest(role="fast", messages=(), cancel_policy="sometimes"), "cancellation"),  # type: ignore[arg-type]
        (ModelRequest(role="fast", messages=(), parameters={"model": "override"}), "controlled fields"),
        (ModelRequest(role="fast", messages=(), response_mode="native"), "native Responses"),
        (ModelRequest(role="fast", messages=(), required_capabilities=frozenset({"vision"})), "lacks capabilities"),
        (
            ModelRequest(
                role="quality",
                messages=(),
                tools=(ToolDefinition("tool", "", {"type": "object"}),),
            ),
            "lacks tools",
        ),
        (
            ModelRequest(
                role="fast",
                messages=(),
                continuation=ModelContinuation("other", "chat_completions"),
            ),
            "continuation",
        ),
    ),
)
def test_gateway_rejects_unsupported_request_contracts(
    project_root: Path, model_request: ModelRequest, message: str
) -> None:
    service = ModelGatewayService(load_configuration(project_root))
    with pytest.raises(ModelCapabilityError, match=message):
        service.negotiate(model_request)


class _FakeGeneration:
    def __init__(self, response: object | None = None, *, cost: float = 0.0, error: Exception | None = None) -> None:
        self.response = response
        self.cost = cost
        self.error = error

    def __await__(self) -> Generator[object, None, object]:
        async def resolve() -> object:
            if self.error is not None:
                raise self.error
            return self.response

        return resolve().__await__()


def _chat_response(content: str, *, tool_calls: list[object] | None = None) -> object:
    message = SimpleNamespace(content=content, reasoning_content="private", tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )


def test_chat_completion_maps_tools_usage_and_continuation(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Caller:
        calls: list[tuple[list[dict[str, object]], dict[str, object]]]

        def __init__(self) -> None:
            self.calls = []

        def acompletion(self, messages: list[dict[str, object]], **kwargs: object) -> _FakeGeneration:
            self.calls.append((messages, kwargs))
            tools = kwargs["tools"]
            assert isinstance(tools, list)
            alias = tools[0]["function"]["name"]
            raw_call = SimpleNamespace(
                id="provider-call",
                function=SimpleNamespace(name=alias, arguments='{"text":"hello"}'),
            )
            return _FakeGeneration(_chat_response('{"kind":"done"}', tool_calls=[raw_call]), cost=_CHAT_COST)

    async def scenario() -> None:
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-secret")
        service = ModelGatewayService(load_configuration(project_root))
        caller = Caller()
        service._gateway = SimpleNamespace(use_model=lambda _role: caller)
        request = ModelRequest(
            role="fast",
            messages=(ModelMessage("user", "hello"),),
            output_schema={"type": "object", "required": ["kind"]},
            tools=(
                ToolDefinition(
                    "org.aurora.console.send_message",
                    "Send text",
                    {"type": "object", "properties": {"text": {"type": "string"}}},
                ),
            ),
        )

        result = await service.complete(request)

        assert result.data == {"kind": "done"}
        assert result.usage == ModelUsage(prompt_tokens=11, completion_tokens=7)
        assert result.cost_usd == _CHAT_COST
        assert result.tool_calls == (ToolCall("provider-call", "org.aurora.console.send_message", {"text": "hello"}),)
        assert result.continuation is not None
        assert result.continuation.channel == "chat_completions"
        assert caller.calls[0][1]["parallel_tool_calls"] is False
        assert "response_format" in caller.calls[0][1]

    asyncio.run(scenario())


def test_chat_structured_output_falls_back_and_enforces_cost_budget(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Caller:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def acompletion(self, _messages: list[dict[str, object]], **kwargs: object) -> _FakeGeneration:
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return _FakeGeneration(error=GatewayError("response_format is unsupported"))
            return _FakeGeneration(_chat_response('{"kind":"fallback"}'), cost=0.5)

    async def scenario() -> None:
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-secret")
        service = ModelGatewayService(load_configuration(project_root))
        caller = Caller()
        service._gateway = SimpleNamespace(use_model=lambda _role: caller)
        request = ModelRequest(
            role="fast",
            messages=(ModelMessage("user", "hello"),),
            output_schema={"type": "object", "required": ["kind"]},
            budget=ModelBudget(max_cost_usd=0.1),
        )

        with pytest.raises(ModelBudgetError, match="max_cost_usd"):
            await service.complete(request)

        assert len(caller.calls) == _EXPECTED_FALLBACK_CALLS
        assert "response_format" in caller.calls[0]
        assert "response_format" not in caller.calls[1]

    asyncio.run(scenario())


def test_responses_completion_maps_native_tool_calls_and_provider_errors(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-secret")
        service = ModelGatewayService(load_configuration(project_root))
        captured: list[dict[str, object]] = []

        async def complete_response(**kwargs: object) -> object:
            captured.append(kwargs)
            tools = kwargs["tools"]
            assert isinstance(tools, list)
            alias = tools[0]["name"]
            return SimpleNamespace(
                output=[
                    {"type": "reasoning", "encrypted_content": "opaque"},
                    {"type": "function_call", "name": alias, "call_id": "native-call", "arguments": {"x": 1}},
                ],
                output_text='{ "kind": "native" }',
                usage=SimpleNamespace(input_tokens=13, output_tokens=5),
                status="completed",
                _hidden_params={"response_cost": _NATIVE_COST},
            )

        monkeypatch.setattr("src.ai.vnext.litellm.aresponses", complete_response)
        request = ModelRequest(
            role="agent",
            messages=(ModelMessage("user", "delegate"),),
            response_mode="native",
            output_schema={"type": "object", "required": ["kind"]},
            tools=(ToolDefinition("org.aurora.worker", "Work", {"type": "object"}),),
        )
        result = await service.complete(request)

        assert result.data == {"kind": "native"}
        assert result.response_mode == "native"
        assert result.tool_calls == (ToolCall("native-call", "org.aurora.worker", {"x": 1}),)
        assert result.usage == ModelUsage(prompt_tokens=13, completion_tokens=5)
        assert result.cost_usd == _NATIVE_COST
        assert result.continuation is not None and result.continuation.channel == "responses"
        assert captured[0]["store"] is False

        provider_error = OSError("provider down")

        async def fail_response(**_kwargs: object) -> object:
            raise provider_error

        monkeypatch.setattr("src.ai.vnext.litellm.aresponses", fail_response)
        with pytest.raises(ModelGatewayError, match="provider down"):
            await service.complete(request)

    asyncio.run(scenario())


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


def _runtime_with_console(project_root: Path) -> AuroraRuntime:
    runtime = AuroraRuntime.create(project_root, executor_bindings=None)
    console = ConsolePlatform()
    runtime.bind_effect_executors(
        (
            EffectExecutorBinding(
                CONSOLE_SEND_DESCRIPTOR,
                console,
                "platform.console",
                "test",
            ),
        )
    )
    return runtime


def test_model_activity_runs_outside_kernel_and_creates_auditable_effect(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime_with_console(project_root)
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
        assert second["effect_receipts_emitted"] == 1
        assert third["ingested_task_ids"]
        assert runtime.kernel.get_task(task_id).status == TaskStatus.COMPLETED  # type: ignore[union-attr]
        await runtime.shutdown()

    asyncio.run(scenario())


def test_invalid_effect_arguments_fail_agent_without_platform_call(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime_with_console(project_root)
        runtime.model_gateway = _ToolGateway({"text": 1})
        await runtime.submit_amp(valid_amp())
        await runtime.pump()
        assert runtime._model_dispatch_task is not None
        await runtime._model_dispatch_task
        result = await runtime.pump()
        assert result["failed_message_ids"]
        assert result["effect_receipts_emitted"] == 0
        await runtime.shutdown()

    asyncio.run(scenario())
