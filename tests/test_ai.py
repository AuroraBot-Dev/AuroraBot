# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from src.ai import models
from src.ai._parsing import (
    chat_assistant_item,
    chat_message,
    chat_tool_calls,
    invalid_output_result,
    json_item,
    parse_arguments,
    provider_tools,
    response_tool_calls,
    responses_usage,
    usage,
)
from src.ai.execution import CostTracker, GatewayError, TaskManager
from src.ai.gateway import ModelGatewayService
from src.config.loader import load_configuration
from src.contracts.model import (
    ModelCapabilityError,
    ModelContinuation,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelResult,
    ModelUsage,
    ToolCall,
    ToolDefinition,
    append_tool_result,
)

if TYPE_CHECKING:
    from pathlib import Path


def _service(project_root: Path) -> ModelGatewayService:
    service = ModelGatewayService(load_configuration(project_root))
    service._capabilities = {
        "fast": frozenset({"chat", "stream", "structured_output", "json_text_fallback", "tools"}),
        "quality": frozenset(
            {"chat", "stream", "structured_output", "json_text_fallback", "tools", "native_responses", "reasoning"}
        ),
        "multimodal": frozenset({"chat", "stream", "vision"}),
        "embedding": frozenset({"embedding"}),
    }
    service._initialized = True
    return service


def test_gateway_negotiates_and_rejects_request_contracts(project_root: Path) -> None:
    service = _service(project_root)
    request = ModelRequest(role="fast", messages=(ModelMessage("user", "test"),), output_schema={"type": "object"})
    assert {"chat", "structured_output"} <= service.negotiate(request)
    assert "chat" in service.negotiate(ModelRequest(role="fast", messages=(), parallel_tool_calls=True))

    invalid = (
        (ModelRequest(role="missing", messages=()), "unknown model role"),
        (ModelRequest(role="fast", messages=(), retry_policy="retry"), "retry_policy"),  # type: ignore[arg-type]
        (ModelRequest(role="fast", messages=(), cancel_policy="sometimes"), "cancellation"),  # type: ignore[arg-type]
        (ModelRequest(role="fast", messages=(), parameters={"model": "override"}), "controlled fields"),
        (ModelRequest(role="fast", messages=(), response_mode="native"), "native Responses"),
        (ModelRequest(role="fast", messages=(), required_capabilities=frozenset({"vision"})), "lacks capabilities"),
        (
            ModelRequest(role="multimodal", messages=(), tools=(ToolDefinition("tool", "", {"type": "object"}),)),
            "lacks tools",
        ),
        (
            ModelRequest(role="fast", messages=(), continuation=ModelContinuation("other", "chat_completions")),
            "continuation",
        ),
    )
    for model_request, message in invalid:
        with pytest.raises(ModelCapabilityError, match=message):
            service.negotiate(model_request)


def test_output_normalization_returns_valid_json_and_configured_fallback(project_root: Path) -> None:
    service = _service(project_root)
    request = ModelRequest(role="fast", messages=(), output_schema={"type": "object", "required": ["kind"]})
    data, diagnostics = service._normalize_output('{"kind":"done"}', request, frozenset({"json_text_fallback"}))
    assert data == {"kind": "done"}
    assert diagnostics == ("output mode: json_text_fallback",)

    fallback = ModelRequest(
        role="fast",
        messages=(),
        output_schema={"type": "object", "required": ["kind"]},
        invalid_output_result={"kind": "no_action"},
    )
    assert service._normalize_output("not JSON", fallback, frozenset())[0] == {"kind": "no_action"}
    assert service._normalize_output('{"other": 1}', fallback, frozenset())[0] == {"kind": "no_action"}


def test_model_contracts_round_trip_and_append_tool_results() -> None:
    request = ModelRequest(
        role="fast",
        messages=(ModelMessage("user", "hello"),),
        tools=(ToolDefinition("echo", "Echo", {"type": "object"}),),
        continuation=ModelContinuation("deepseek", "chat_completions", ({"role": "assistant"},)),
    )
    assert ModelRequest.from_dict(request.to_dict()) == request

    result = ModelResult(
        "model",
        frozenset({"chat"}),
        "normalized",
        "ok",
        None,
        ModelUsage(2, 3),
        0.1,
        tool_calls=(ToolCall("call", "echo", {"text": "x"}),),
        continuation=request.continuation,
    )
    assert ModelResult.from_dict(result.to_dict()) == result
    continuation = request.continuation
    assert continuation is not None
    chat = append_tool_result(continuation, "call", {"ok": True}, is_error=False)
    responses = append_tool_result(ModelContinuation("openai", "responses"), "call", "bad", is_error=True)
    assert chat.items[-1]["role"] == "tool"
    assert responses.items[-1]["type"] == "function_call_output"
    with pytest.raises(ValueError, match="channel"):
        ModelContinuation.from_dict({"provider": "x", "channel": "bad"})


def test_parsing_maps_provider_tools_and_tool_calls() -> None:
    definitions = (ToolDefinition("org.example.echo", "Echo", {"type": "object"}),)
    chat_defs, aliases = provider_tools(definitions, responses=False)
    response_defs, response_aliases = provider_tools(definitions, responses=True)
    alias = next(iter(aliases))
    assert alias == "org_example_echo"
    assert chat_defs[0]["function"]["name"] == alias
    assert response_defs[0]["name"] == alias
    assert response_aliases == aliases

    raw_call = SimpleNamespace(id="call", function=SimpleNamespace(name=alias, arguments='{"text":"hello"}'))
    message = SimpleNamespace(content="ok", reasoning_content="private", tool_calls=[raw_call])
    calls, diagnostics = chat_tool_calls(message, aliases)
    assert calls == (ToolCall("call", "org.example.echo", {"text": "hello"}),)
    assert diagnostics == ()
    assert chat_assistant_item(message)["reasoning_content"] == "private"

    response_calls, diagnostics = response_tool_calls(
        ({"type": "function_call", "name": alias, "call_id": "native", "arguments": {"x": 1}},), aliases
    )
    assert response_calls == (ToolCall("native", "org.example.echo", {"x": 1}),)
    assert diagnostics == ()


def test_parsing_handles_malformed_provider_values() -> None:
    diagnostics: list[str] = []
    assert parse_arguments("[1]", diagnostics) == {}
    assert parse_arguments("{", diagnostics) == {}
    assert len(diagnostics) == 2
    calls, call_diagnostics = chat_tool_calls(
        SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name="unknown", arguments="{}"))]), {}
    )
    assert calls == () and call_diagnostics
    with pytest.raises(ModelGatewayError, match="no assistant"):
        chat_message(SimpleNamespace(choices=[]))
    assert json_item({"type": "reasoning"}) == {"type": "reasoning"}
    assert json_item(SimpleNamespace(type="message")) == {"type": "message"}


def test_usage_helpers_and_invalid_output_fallback() -> None:
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=4, completion_tokens=5))
    native = SimpleNamespace(usage=SimpleNamespace(input_tokens=6, output_tokens=7))
    assert usage(response) == ModelUsage(4, 5)
    assert responses_usage(native) == ModelUsage(6, 7)
    request = ModelRequest(
        role="fast",
        messages=(),
        output_schema={"type": "object", "required": ["kind"]},
        invalid_output_result={"wrong": True},
    )
    assert invalid_output_result(request, "bad")[0] is None


def test_model_call_without_credential_is_rejected_before_provider(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        service = _service(project_root)
        with pytest.raises(ModelGatewayError, match="missing model credential"):
            await service.complete(ModelRequest(role="fast", messages=(ModelMessage("user", "test"),)))

    asyncio.run(scenario())


def test_cost_tracker_and_task_manager() -> None:
    async def scenario() -> None:
        tracker = CostTracker()
        await tracker.add({"role": "fast", "model": "m", "cost": 0.25})
        await tracker.add({"role": "fast", "model": "m", "cost": 0.5})
        summary = await tracker.summary()
        assert summary["total_cost"] == 0.75
        assert summary["by_role"]["fast"]["count"] == 2

        manager = TaskManager()

        async def wait() -> tuple[str, float]:
            await asyncio.sleep(10)
            return "never", 0.0

        generation = manager.create_task(wait())
        await asyncio.sleep(0)
        assert manager.abort(generation.task_id)
        with pytest.raises(asyncio.CancelledError):
            await generation
        assert not manager.abort("missing")
        manager.abort_all()

    asyncio.run(scenario())


def test_models_dev_capabilities_pricing_and_disk_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = {
        "provider": {
            "models": {
                "model": {
                    "tool_call": True,
                    "reasoning": True,
                    "structured_output": True,
                    "modalities": {"input": ["text", "image"]},
                    "cost": {"input": 2.0, "output": 4.0},
                }
            }
        }
    }
    monkeypatch.setattr(models, "_cache", {"provider/model": raw["provider"]["models"]["model"]})
    monkeypatch.setattr(models, "_cache_ts", models.time.monotonic())
    models.init_cache(tmp_path)

    async def scenario() -> None:
        assert await models.get_pricing_by_id("provider/model") == {"input": 2.0, "output": 4.0}
        assert await models.compute_cost("provider/model", 1_000_000, 500_000) == 4.0
        capabilities = await models.get_capabilities_by_id("provider/model")
        assert {"chat", "tools", "reasoning", "structured_output", "vision"} <= capabilities
        assert await models.get_model_info("missing") is None

    asyncio.run(scenario())
    legacy = tmp_path / "models-dev-20000101-00.json"
    legacy.write_text("{}", encoding="utf-8")
    models._write_cache(raw)
    cached, _timestamp = models._find_valid_cache()
    assert cached == raw
    assert not legacy.exists()
    assert len(tuple(tmp_path.glob("models-dev-*.json.gz"))) == 1


def test_gateway_error_preserves_retryability() -> None:
    assert GatewayError("temporary", retryable=True).retryable
