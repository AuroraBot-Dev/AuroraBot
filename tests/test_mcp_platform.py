from __future__ import annotations

import asyncio
from pathlib import Path

from src.contracts.amp import new_amp
from src.contracts.model import ModelContinuation, ModelRequest, ModelResult, ModelUsage, ToolCall
from src.localhost.runtime import AuroraRuntime


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


def test_clock_mcp_activity_receipt_resumes_requesting_agent(project_root: Path) -> None:
    source_root = Path(__file__).parents[1]
    app_directory = (source_root / "src" / "apps" / "aurora-app-clock").as_posix()
    (project_root / "config" / "apps.toml").write_text(
        f"""adapter = []

[[app]]
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
        runtime = AuroraRuntime.create(project_root)
        gateway = _ClockGateway()
        runtime.model_gateway = gateway
        try:
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
            assert second["platform_receipts_emitted"] == 1
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
            await runtime.shutdown()

    asyncio.run(scenario())
