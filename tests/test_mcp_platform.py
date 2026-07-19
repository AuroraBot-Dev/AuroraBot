from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from src.contracts.amp import AmpEnvelope, new_amp
from src.contracts.configuration import load_configuration
from src.contracts.model import ModelContinuation, ModelRequest, ModelResult, ModelUsage, ToolCall
from src.localhost.ports import EffectExecutionRequest, EffectExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.mcp import MCPPlatform
from src.utils.log_utils import configure_console_logging, configure_logging

if TYPE_CHECKING:
    from src.platform.mcp.server_spec import MCPServerSpec


@dataclass(slots=True)
class _Ingress:
    values: list[object] = field(default_factory=list)

    async def submit_amp(self, value: object) -> str:
        self.values.append(value)
        return AmpEnvelope.parse(value).header.message_id


class _StartupError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("startup failed")


class _ClockGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResult:
        self.calls += 1
        tool_calls = ()
        continuation = None
        if self.calls == 1:
            tool_calls = (ToolCall("clock-call", "org.aurora.clock.get_current_time", {}),)
            continuation = ModelContinuation("test", "chat_completions", ())
        return ModelResult(
            model="test/clock",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode=request.response_mode,
            text="clock checked" if self.calls > 1 else "",
            data=None,
            usage=ModelUsage(),
            cost_usd=0,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            continuation=continuation,
        )


def test_mcp_tool_is_error_returns_failed_effect_outcome(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        platform = MCPPlatform(load_configuration(project_root))

        async def call_tool(_capability: str, _parameters: dict[str, object]) -> dict[str, object]:
            return {"is_error": True, "text": "tool rejected request"}

        monkeypatch.setattr(platform, "_call_tool", call_tool)
        platform._started = True
        outcome = await platform.execute_effect(EffectExecutionRequest("request", "session", "test.tool", {}))

        assert outcome.succeeded is False
        assert outcome.error is not None and "tool rejected request" in outcome.error
        await platform.shutdown()

    asyncio.run(scenario())


def test_mcp_notification_uses_external_ingress(project_root: Path) -> None:
    async def scenario() -> None:
        ingress = _Ingress()
        platform = MCPPlatform(load_configuration(project_root))
        platform._ingress = ingress

        await platform._handle_notification(
            "org.example.app",
            "aurora/event",
            {"type": "example.changed", "summary": "changed", "data": {"value": 1}},
        )

        event = AmpEnvelope.parse(ingress.values[0])
        assert event.payload.type == "example.changed"
        assert event.header.source["app"] == "org.example.app"

    asyncio.run(scenario())


def test_mcp_start_failure_rolls_back_started_resources(project_root: Path) -> None:
    async def scenario() -> None:
        ingress = _Ingress()
        platform = MCPPlatform(load_configuration(project_root))

        class FailingKit:
            stopped = False

            async def start_all(self, _specs: list[MCPServerSpec]) -> None:
                raise _StartupError

            async def stop_all(self) -> None:
                self.stopped = True

        kit = FailingKit()
        platform._kit = kit  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="startup failed"):
            await platform.start(ingress)

        assert kit.stopped is True
        assert platform._ingress is None

    asyncio.run(scenario())


def test_clock_mcp_activity_receipt_resumes_requesting_agent(
    project_root: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    source_root = Path(__file__).parents[1]
    app_directory = (source_root / "src" / "apps" / "aurora-app-clock").as_posix()
    (project_root / "config" / "apps.toml").write_text(
        f"""[[app]]
package = "org.aurora.clock"
enabled = true
transport = "stdio"
working_dir = "{app_directory}"
command = ["uv", "run", "python", "mcp_server.py"]
timeout_seconds = 30

[[app.tool]]
name = "org.aurora.clock.get_current_time"
result_mode = "resume"

[[app.tool]]
name = "org.aurora.clock.set_alarm"
result_mode = "resume"

[[app.tool]]
name = "org.aurora.clock.set_timer"
result_mode = "resume"

[[app.tool]]
name = "org.aurora.clock.list_alarms"
result_mode = "resume"

[[app.tool]]
name = "org.aurora.clock.cancel_alarm"
result_mode = "resume"
""",
        encoding="utf-8",
    )
    agents = project_root / "config" / "agents.toml"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            'capabilities = ["org.aurora.console.send_message"]',
            'capabilities = ["org.aurora.clock.get_current_time"]',
        ),
        encoding="utf-8",
    )

    async def scenario() -> None:
        configuration = load_configuration(project_root)
        configure_logging(configuration.logging_level, configuration.root / "logs" / "aurora.log")
        configure_console_logging(enabled=False)
        runtime = AuroraRuntime.create(project_root, configuration=configuration, executor_bindings=None)
        platform = MCPPlatform(runtime.configuration)
        gateway = _ClockGateway()
        runtime.model_gateway = gateway
        try:
            catalog = await platform.start(runtime)
            assert catalog is platform.capability_catalog
            runtime.bind_effect_executors(
                tuple(
                    EffectExecutorBinding(capability, platform, "platform.mcp", "org.aurora.clock")
                    for capability in catalog.capabilities
                )
            )
            await runtime.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="test:clock",
                    summary="what time is it",
                    data={"text": "what time is it"},
                    source_app="tests",
                    source_instance="mcp",
                ).to_dict()
            )
            first = await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            second = await runtime.pump()
            assert second["effect_receipts_emitted"] == 1
            await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            fourth = await runtime.pump()
            task = runtime.task(first["ingested_task_ids"][0])
            assert task is not None
            assert any(event["type"] == "effect.succeeded" for event in task["events"])
            expected_calls = 2
            assert gateway.calls == expected_calls
            assert fourth["processed_message_ids"]
        finally:
            await platform.shutdown()
            await runtime.shutdown()

    asyncio.run(scenario())
    captured = capfd.readouterr()
    assert "Agent Kernel initialized" not in captured.err
    assert "Processing request of type ListToolsRequest" not in captured.err
    assert "Starting Clock MCP server" in (project_root / "logs" / "aurora.log").read_text(encoding="utf-8")
