from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from src.ai.contracts import (
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
from src.ai.gateway import GatewayError
from src.ai.vnext import ModelGatewayService
from src.kernel.episodes import EpisodeSnapshot, EpisodeStatus
from src.localhost.configuration import SchedulerConfig, load_configuration
from src.localhost.runtime import AuroraRuntime
from src.localhost.scheduler import CognitiveScheduler
from tests.test_events import valid_amp

if TYPE_CHECKING:
    from pathlib import Path


def _enable_first_loop(project_root: Path) -> None:
    aurora = project_root / "config" / "aurora.toml"
    content = aurora.read_text(encoding="utf-8")
    content = content.replace(
        'capabilities = ["chat", "stream", "structured_output", "json_text_fallback"]',
        'capabilities = ["chat", "stream", "structured_output", "json_text_fallback", "tools"]',
        1,
    )
    content += """

[models.roles.agent]
provider = "test"
model = "agent"
endpoint = "responses"
capabilities = ["chat", "tools", "native_responses", "reasoning"]
"""
    aurora.write_text(content, encoding="utf-8")
    (project_root / "config" / "nodes.toml").write_text(
        """[[node]]
id = "builtin.fast_gate"
enabled = true
implementation = "src.nodes.fast_gate:FastGateNode"
inputs = ["message.received", "model.completed", "model.failed", "effect.succeeded", "effect.failed"]
outputs = ["model.requested", "effect.requested", "cognition.escalated", "episode.ended"]
capabilities = ["org.aurora.console.send_message"]
model_roles = ["fast"]

[[node]]
id = "builtin.native_agent"
enabled = true
implementation = "src.nodes.native_agent:NativeAgentNode"
inputs = ["cognition.escalated", "model.completed", "model.failed", "effect.succeeded", "effect.failed"]
outputs = ["model.requested", "effect.requested", "episode.ended"]
capabilities = ["org.aurora.console.send_message"]
model_roles = ["agent"]

[[edge]]
event_type = "message.received"
target = "builtin.fast_gate"

[[edge]]
event_type = "cognition.escalated"
target = "builtin.native_agent"
advances_round = true

[[edge]]
event_type = "model.completed"
target = "@continuation"
advances_round = true

[[edge]]
event_type = "model.failed"
target = "@continuation"
advances_round = true

[[edge]]
event_type = "effect.succeeded"
target = "@continuation"
advances_round = true

[[edge]]
event_type = "effect.failed"
target = "@continuation"
advances_round = true
""",
        encoding="utf-8",
    )
    (project_root / "config" / "apps.toml").write_text(
        """app = []

[[adapter]]
id = "local.test"
enabled = true
implementation = "src.platform.local:LocalTestPlatform"

[[adapter.capability]]
id = "org.aurora.console.send_message"
description = "Publish text to the local console"
result_mode = "terminal"
parameters_schema = { type = "object", properties = { text = { type = "string" } }, required = ["text"], additionalProperties = false }
""",
        encoding="utf-8",
    )


class _SequenceGateway:
    def __init__(self, calls: list[ToolCall | None]) -> None:
        self.calls = calls
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResult:
        self.requests.append(request)
        call = self.calls.pop(0)
        channel = "responses" if request.response_mode == "native" else "chat_completions"
        continuation = ModelContinuation("test", channel, ({"role": "assistant", "content": "internal"},))
        return ModelResult(
            model=f"test/{request.role}",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode=request.response_mode,
            text="internal",
            data=None,
            usage=ModelUsage(10, 2),
            cost_usd=0.0,
            tool_calls=(call,) if call is not None else (),
            finish_reason="tool_calls" if call is not None else "stop",
            continuation=continuation,
        )


def test_fast_gate_terminal_effect_closes_episode_across_cycles(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        runtime = AuroraRuntime.create(project_root)
        gateway = _SequenceGateway([ToolCall("call-send", "org.aurora.console.send_message", {"text": "hello"})])
        runtime.kernel._model_gateway = gateway
        try:
            await runtime.submit_amp(valid_amp())
            first = await runtime.run_cycle()
            assert not first["platform_receipts_emitted"]
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task

            second = await runtime.run_cycle()
            assert second["platform_receipts_emitted"] == 1
            third = await runtime.run_cycle()
            episode = runtime.kernel.get_episode(runtime.kernel.get_record(first["ingested_record_ids"][0]).episode_id)
            assert episode is not None
            assert episode.status == EpisodeStatus.COMPLETED
            assert episode.termination_reason == "terminal_effect_succeeded"
            assert third["ingested_record_ids"]
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_fast_gate_can_escalate_to_native_agent_and_end_silent(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        runtime = AuroraRuntime.create(project_root)
        gateway = _SequenceGateway([ToolCall("call-up", "aurora.cognition.escalate", {"reason": "complex"}), None])
        runtime.kernel._model_gateway = gateway
        try:
            await runtime.submit_amp(valid_amp())
            await runtime.run_cycle()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            await runtime.run_cycle()
            await runtime.run_cycle()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            await runtime.run_cycle()
            episode = next(iter(runtime.kernel.episodes()))
            assert episode.status == EpisodeStatus.SILENT
            assert [request.role for request in gateway.requests] == ["fast", "agent"]
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_resume_effect_replays_tool_result_in_same_episode(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        apps = project_root / "config" / "apps.toml"
        apps.write_text(apps.read_text(encoding="utf-8").replace('result_mode = "terminal"', 'result_mode = "resume"'))
        runtime = AuroraRuntime.create(project_root)
        gateway = _SequenceGateway(
            [ToolCall("call-send", "org.aurora.console.send_message", {"text": "observe"}), None]
        )
        runtime.kernel._model_gateway = gateway
        try:
            await runtime.submit_amp(valid_amp())
            await runtime.run_cycle()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            await runtime.run_cycle()
            await runtime.run_cycle()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            await runtime.run_cycle()
            assert len(gateway.requests) == 2
            continuation = gateway.requests[1].continuation
            assert continuation is not None
            assert continuation.items[-1]["role"] == "tool"
            assert next(iter(runtime.kernel.episodes())).status == EpisodeStatus.SILENT
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 15, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def test_scheduler_backs_off_and_external_activity_resets(project_root: Path) -> None:
    clock = _Clock()
    config = SchedulerConfig()
    scheduler = CognitiveScheduler(project_root / "scheduler.json", config, now=clock)
    assert not scheduler.can_tick(())
    clock.value += timedelta(seconds=30)
    assert scheduler.can_tick(())
    scheduler.mark_tick_emitted()
    episode = EpisodeSnapshot(
        episode_id="episode",
        root_record_id="root",
        autonomous=True,
        status=EpisodeStatus.SILENT,
        active_node_id="builtin.fast_gate",
        round=1,
        model_calls=1,
        tool_calls=0,
        max_model_calls=3,
        max_tool_calls=2,
        max_duration_seconds=120,
        started_at=clock.value.isoformat(),
        updated_at=clock.value.isoformat(),
    )
    scheduler.reconcile((episode,))
    assert scheduler.state.current_interval_seconds == 60
    scheduler.on_external_activity()
    assert scheduler.state.current_interval_seconds == 30


def test_responses_adapter_is_stateless_serial_and_restores_capability_name(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-key")
        captured: dict[str, object] = {}

        async def fake_responses(**kwargs: object) -> object:
            captured.update(kwargs)
            tools = kwargs["tools"]
            assert isinstance(tools, list)
            alias = tools[0]["name"]
            return SimpleNamespace(
                output_text="",
                status="completed",
                output=[
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": alias,
                        "arguments": '{"text":"hello"}',
                    }
                ],
                usage=SimpleNamespace(input_tokens=5, output_tokens=2),
                _hidden_params={"response_cost": 0.01},
            )

        monkeypatch.setattr("src.ai.vnext.litellm.aresponses", fake_responses)
        service = ModelGatewayService(load_configuration(project_root))
        result = await service.complete(
            ModelRequest(
                role="agent",
                response_mode="native",
                messages=(ModelMessage("user", "publish"),),
                required_capabilities=frozenset({"chat", "tools"}),
                tools=(
                    ToolDefinition(
                        "org.aurora.console.send_message",
                        "publish",
                        {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    ),
                ),
            )
        )
        assert captured["store"] is False
        assert captured["parallel_tool_calls"] is False
        assert captured["include"] == ["reasoning.encrypted_content"]
        assert result.tool_calls[0].name == "org.aurora.console.send_message"
        assert result.continuation is not None
        assert result.continuation.items[0] == {"role": "user", "content": "publish"}

    asyncio.run(scenario())


def test_chat_adapter_uses_native_serial_tools_and_preserves_reasoning(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-key")
        service = ModelGatewayService(load_configuration(project_root))
        captured: dict[str, object] = {}

        class ProviderToolCall:
            id = "call-1"
            function = SimpleNamespace(name="", arguments='{"text":"hello"}')

            def model_dump(self, *, mode: str) -> dict[str, object]:
                assert mode == "json"
                return {
                    "id": self.id,
                    "type": "function",
                    "function": {
                        "name": self.function.name,
                        "arguments": self.function.arguments,
                    },
                }

        async def fake_chat(
            _caller: object,
            messages: list[dict[str, object]],
            _request: ModelRequest,
            kwargs: dict[str, object],
            _negotiated: frozenset[str],
        ) -> tuple[object, object]:
            captured["messages"] = messages
            captured.update(kwargs)
            tools = kwargs["tools"]
            assert isinstance(tools, list)
            tool_call = ProviderToolCall()
            tool_call.function.name = tools[0]["function"]["name"]
            message = SimpleNamespace(content="", reasoning_content="reasoning", tool_calls=[tool_call])
            response = SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
            )
            return SimpleNamespace(cost=0.01), response

        monkeypatch.setattr(service, "_complete_chat_with_fallback", fake_chat)
        result = await service.complete(
            ModelRequest(
                role="fast",
                messages=(ModelMessage("user", "publish"),),
                required_capabilities=frozenset({"chat", "tools"}),
                tools=(
                    ToolDefinition(
                        "org.aurora.console.send_message",
                        "publish",
                        {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    ),
                ),
            )
        )
        assert captured["parallel_tool_calls"] is False
        assert captured["tool_choice"] == "auto"
        assert result.tool_calls[0].name == "org.aurora.console.send_message"
        assert result.continuation is not None
        assert result.continuation.items[-1]["reasoning_content"] == "reasoning"

    asyncio.run(scenario())


def test_chat_structured_output_falls_back_only_for_provider_support_error(project_root: Path) -> None:
    async def scenario() -> None:
        service = ModelGatewayService(load_configuration(project_root))

        class Caller:
            def __init__(self) -> None:
                self.kwargs: list[dict[str, object]] = []

            def acompletion(self, _messages: object, **kwargs: object) -> object:
                self.kwargs.append(kwargs)

                async def result() -> object:
                    if len(self.kwargs) == 1:
                        raise GatewayError("response_format unsupported")
                    return "fallback-response"

                return result()

        caller = Caller()
        request = ModelRequest(
            role="fast",
            messages=(ModelMessage("user", "structured"),),
            output_schema={"type": "object"},
        )
        _task, response = await service._complete_chat_with_fallback(
            caller,
            [{"role": "user", "content": "structured"}],
            request,
            {"response_format": {"type": "json_schema"}},
            frozenset({"structured_output"}),
        )
        assert response == "fallback-response"
        assert "response_format" in caller.kwargs[0]
        assert "response_format" not in caller.kwargs[1]

    asyncio.run(scenario())


def test_responses_provider_failure_is_normalized(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-key")

        async def fail(**_kwargs: object) -> object:
            raise TimeoutError("provider timeout")

        monkeypatch.setattr("src.ai.vnext.litellm.aresponses", fail)
        service = ModelGatewayService(load_configuration(project_root))
        with pytest.raises(ModelGatewayError, match="Responses request failed"):
            await service.complete(ModelRequest(role="agent", messages=(), response_mode="native"))

    asyncio.run(scenario())


def test_responses_invalid_tool_arguments_are_audited(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _enable_first_loop(project_root)
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-key")

        async def fake_responses(**kwargs: object) -> object:
            tools = kwargs["tools"]
            return SimpleNamespace(
                output_text="",
                status="completed",
                output=[
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": tools[0]["name"],
                        "arguments": "not-json",
                    }
                ],
                usage=None,
                _hidden_params={},
            )

        monkeypatch.setattr("src.ai.vnext.litellm.aresponses", fake_responses)
        service = ModelGatewayService(load_configuration(project_root))
        result = await service.complete(
            ModelRequest(
                role="agent",
                messages=(),
                response_mode="native",
                tools=(ToolDefinition("clock.now", "clock", {"type": "object"}),),
            )
        )
        assert result.tool_calls[0].arguments == {}
        assert "not valid JSON" in result.diagnostics[0]

    asyncio.run(scenario())


def test_completed_call_over_cost_budget_is_rejected(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("AURORA_TEST_MODEL_API_KEY", "test-key")
        service = ModelGatewayService(load_configuration(project_root))

        async def expensive(_request: ModelRequest, _role: object, _negotiated: frozenset[str]) -> ModelResult:
            return ModelResult(
                model="test/fast",
                negotiated_capabilities=frozenset({"chat"}),
                response_mode="normalized",
                text="",
                data=None,
                usage=ModelUsage(),
                cost_usd=1.0,
            )

        monkeypatch.setattr(service, "_complete_chat", expensive)
        with pytest.raises(ModelBudgetError, match="cost"):
            await service.complete(
                ModelRequest(
                    role="fast",
                    messages=(),
                    budget=ModelBudget(max_cost_usd=0.1),
                )
            )

    asyncio.run(scenario())
