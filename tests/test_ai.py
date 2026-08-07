# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
import time
import urllib.error
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from src.ai import models
from src.ai.execution import CostTracker, GatewayError
from src.ai.gateway import ModelGatewayService, invalid_output_result
from src.ai.roles.base import (
    RoleHandler,
    _provider_tool_alias,
    build_chat_kwargs,
    chat_assistant_item,
    chat_message,
    chat_tool_calls,
    complete_chat_with_fallback,
    json_item,
    parse_arguments,
    parse_chat_response,
    provider_tools,
    usage,
)
from src.config.loader import load_configuration
from src.contracts import (
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

    from src.contracts.configuration import ModelRoleConfig


def _service(project_root: Path) -> ModelGatewayService:
    service = ModelGatewayService(load_configuration(project_root))
    service._capabilities = {
        "fast": frozenset({"chat", "stream", "structured_output", "json_text_fallback", "tools"}),
        "quality": frozenset({"chat", "stream", "structured_output", "json_text_fallback", "tools", "reasoning"}),
        "multimodal": frozenset({"chat", "stream", "vision"}),
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
        (ModelRequest(role="fast", messages=(), required_capabilities=frozenset({"vision"})), "lacks capabilities"),
        (
            ModelRequest(role="multimodal", messages=(), tools=(ToolDefinition("tool", "", {"type": "object"}),)),
            "lacks capabilities",
        ),
        (
            ModelRequest(role="fast", messages=(), continuation=ModelContinuation("other", "chat_completions")),
            "continuation",
        ),
    )
    for model_request, message in invalid:
        with pytest.raises(ModelCapabilityError, match=message):
            service.negotiate(model_request)


def test_role_baseline_and_adapt_request_hooks(project_root: Path) -> None:
    """RFC 0213：能力基线并入能力集；adapt_request 可改写请求。"""

    from src.ai.roles.base import RoleHandler
    from src.ai.roles.quality import QualityRole

    service = _service(project_root)
    service._capabilities = {
        "fast": frozenset({"chat", "stream", "tools"}),
        "quality": frozenset({"chat", "stream", "tools"}),
        "multimodal": frozenset({"chat", "stream", "vision"}),
    }
    service._initialized = True
    # 能力基线合并：quality 声明 reasoning，即使 models.dev 未标注也可协商
    assert "reasoning" in service._capabilities_for("quality")
    assert service.negotiate(
        ModelRequest(role="quality", messages=(), required_capabilities=frozenset({"reasoning"}))
    ) >= {"reasoning"}
    # adapt_request 默认原样返回
    request = ModelRequest(role="fast", messages=())
    assert QualityRole().adapt_request(request) is request
    assert QualityRole.capability_baseline == frozenset({"reasoning"})
    assert issubclass(QualityRole, RoleHandler)


def test_role_self_contained_implementation(project_root: Path) -> None:
    """RFC 0214：角色文件自包含完整实现，可独立扩展（如音频输出）。"""

    class AudioMultimodalRole(RoleHandler):
        """模拟多模态角色的音频输出适配：完整实现，独立于其他角色。"""

        endpoint = "chat_completions"
        capability_baseline = frozenset({"vision", "audio"})

        async def complete(
            self,
            gateway: ModelGatewayService,
            request: ModelRequest,
            role: ModelRoleConfig,
            negotiated: frozenset[str],
        ) -> ModelResult:  # type: ignore[override]
            capabilities = gateway._capabilities_for(request.role)
            messages, kwargs, alias_to_name = build_chat_kwargs(request, negotiated)
            # 多模态扩展点：音频输出参数
            kwargs["modalities"] = ["text", "audio"]
            caller = gateway._caller_for(request.role)
            task, response = await complete_chat_with_fallback(
                caller, messages, request, kwargs, negotiated, capabilities
            )
            return parse_chat_response(gateway, request, role, negotiated, response, task, alias_to_name)

    service = _service(project_root)
    service._handlers["multimodal"] = AudioMultimodalRole()
    assert service._capabilities_for("multimodal") >= {"vision", "audio"}
    request = ModelRequest(role="multimodal", messages=(), parameters={"text": "hi"})
    assert AudioMultimodalRole().adapt_request(request) is request
    _messages, kwargs, _aliases = build_chat_kwargs(request, frozenset())
    assert "modalities" not in kwargs  # 共享函数不含多模态参数，扩展在角色文件内


def test_get_response_returns_unwrapped_output(project_root: Path) -> None:
    """RFC 0215：get_response 返回脱壳 dict（text/tool_calls/finish_reason）。"""
    from src.ai.roles.embedding import EmbeddingRole

    service = _service(project_root)

    async def fake_complete(request: ModelRequest) -> ModelResult:
        assert request.messages[0].content == "hi"
        return ModelResult(
            model="provider/model",
            negotiated_capabilities=frozenset({"chat"}),
            response_mode="normalized",
            text="hello",
            data=None,
            usage=ModelUsage(1, 1),
            cost_usd=0.0,
            diagnostics=(),
            tool_calls=(ToolCall("call-1", "aur.tool", {"x": 1}),),
            finish_reason="tool_calls",
            continuation=None,
        )

    service.complete = fake_complete  # type: ignore[method-assign]
    result = asyncio.run(service.get_response("fast", [{"role": "user", "content": "hi"}]))
    assert result["text"] == "hello"
    assert result["tool_calls"] == [{"call_id": "call-1", "name": "aur.tool", "arguments": {"x": 1}}]
    assert result["finish_reason"] == "tool_calls"

    # embedding 角色：get_response 走 embed 路径
    class FakeEmbedding(EmbeddingRole):
        async def embed(self, gateway: object, inputs: list[str]) -> list[list[float]]:  # noqa: ARG002
            return [[0.1, 0.2]] * len(inputs)

    service._handlers["embedding"] = FakeEmbedding()
    embedding_result = asyncio.run(service.get_response("embedding", ["text one", "text two"]))
    assert len(embedding_result["embeddings"]) == 2
    assert embedding_result["model"] == service._models["embedding"]


def test_export_openai_client_and_cost_stats(project_root: Path) -> None:
    """RFC 0215：client 可导出；CostTracker 提供总费用与分类统计。"""
    from src.ai.execution import CostTracker

    service = _service(project_root)
    client = service.export_openai_client()
    assert client is not None

    async def scenario() -> None:
        tracker = CostTracker()
        await tracker.add({"role": "fast", "model": "m1", "status": "completed", "cost": 0.5})
        await tracker.add({"role": "fast", "model": "m1", "status": "completed", "cost": 0.3})
        await tracker.add({"role": "quality", "model": "m2", "status": "completed", "cost": 1.2})
        assert await tracker.total_cost() == 2.0
        assert await tracker.by_role() == {"fast": {"count": 2, "cost": 0.8}, "quality": {"count": 1, "cost": 1.2}}
        assert await tracker.by_model() == {"m1": {"count": 2, "cost": 0.8}, "m2": {"count": 1, "cost": 1.2}}

    asyncio.run(scenario())


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
    alias = next(iter(aliases))
    assert alias == "org__example__echo"
    # 双下划线替换与原始单下划线不混淆（RFC 0214 歧义消除）
    assert _provider_tool_alias("aur_agent_delegate") == "aur_agent_delegate"
    assert _provider_tool_alias("aur.agent.delegate") == "aur__agent__delegate"
    assert _provider_tool_alias("aur_agent.delegate") == "aur_agent__delegate"
    assert chat_defs[0]["function"]["name"] == alias

    raw_call = SimpleNamespace(id="call", function=SimpleNamespace(name=alias, arguments='{"text":"hello"}'))
    message = SimpleNamespace(content="ok", reasoning_content="private", tool_calls=[raw_call])
    calls, diagnostics = chat_tool_calls(message, aliases)
    assert calls == (ToolCall("call", "org.example.echo", {"text": "hello"}),)
    assert diagnostics == ()
    assert chat_assistant_item(message)["reasoning_content"] == "private"


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
    assert usage(response) == ModelUsage(4, 5)
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


def test_cost_tracker() -> None:
    async def scenario() -> None:
        tracker = CostTracker()
        await tracker.add({"role": "fast", "model": "m", "cost": 0.25})
        await tracker.add({"role": "fast", "model": "m", "cost": 0.5})
        summary = await tracker.summary()
        assert summary["total_cost"] == 0.75
        assert summary["by_role"]["fast"]["count"] == 2

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
        assert await models.get_modalities_by_id("provider/model") == (frozenset({"text", "image"}), frozenset())
        assert await models.get_modalities_by_id("missing") == (frozenset(), frozenset())

    asyncio.run(scenario())
    legacy = tmp_path / "models-dev-20000101-00.json"
    legacy.write_text("{}", encoding="utf-8")
    models._write_cache(raw)
    cached, fresh = models._find_disk_cache()
    assert cached == raw
    assert fresh is True
    assert not legacy.exists()
    assert len(tuple(tmp_path.glob("models-dev-*.json.gz"))) == 1


def test_models_dev_slow_network_never_blocks_getters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """慢网络下查询立即返回当前可用缓存，刷新在后台进行。"""
    monkeypatch.setattr(models, "_cache", None)
    monkeypatch.setattr(models, "_cache_ts", 0.0)
    monkeypatch.setattr(models, "_refresh_task", None)
    models.init_cache(tmp_path)

    def slow_fetch() -> dict[str, Any]:
        time.sleep(0.2)
        raise urllib.error.URLError("slow network")

    monkeypatch.setattr(models, "_fetch", slow_fetch)

    async def scenario() -> None:
        started = time.monotonic()
        caps = await models.get_capabilities_by_id("provider/model")
        assert caps == models._IMPLICIT_CAPABILITIES
        assert time.monotonic() - started < 0.1
        assert models._refresh_task is not None

        started = time.monotonic()
        assert await models.refresh_now(wait_seconds=0.05) is False
        assert time.monotonic() - started < 0.1
        assert await models.cache_available() is False

        if models._refresh_task is not None:
            await asyncio.shield(models._refresh_task)

    asyncio.run(scenario())


def test_gateway_cold_start_falls_back_and_opens_tools(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """冷启动且 models.dev 不可用时：短时限等待后使用隐含能力继续对话。"""

    def offline() -> dict[str, Any]:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(models, "_fetch", offline)
    monkeypatch.setattr(models, "_cache", None)
    monkeypatch.setattr(models, "_cache_ts", 0.0)
    monkeypatch.setattr(models, "_refresh_task", None)

    async def _no_cache() -> bool:
        return False

    async def _no_refresh(wait_seconds: float) -> bool:
        _ = wait_seconds
        return False

    monkeypatch.setattr("src.ai.gateway.cache_available", _no_cache)
    monkeypatch.setattr("src.ai.gateway.refresh_now", _no_refresh)

    async def scenario() -> None:
        service = ModelGatewayService(load_configuration(project_root))
        try:
            await service.initialize()
            assert "fast" in service._uncertain_roles
            assert "quality" not in service._uncertain_roles
            request = ModelRequest(
                role="fast",
                messages=(),
                tools=(ToolDefinition("t", "", {"type": "object"}),),
            )
            assert "tools" in service.negotiate(request)
        finally:
            if models._refresh_task is not None:
                await asyncio.shield(models._refresh_task)

    asyncio.run(scenario())


def test_gateway_error_preserves_retryability() -> None:
    assert GatewayError("temporary", retryable=True).retryable
