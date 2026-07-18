from __future__ import annotations

import asyncio
from pathlib import Path

from src.contracts.amp import new_amp
from src.contracts.model import ModelRequest, ModelResult, ModelUsage, ToolCall
from src.localhost.runtime import AuroraRuntime
from src.localhost.shell import run_console


def test_console_mcp_tool_delivers_text_to_the_interactive_shell(project_root: Path) -> None:
    source_root = Path(__file__).parents[1]
    app_directory = (source_root / "src" / "apps" / "aurora-app-console").as_posix()
    (project_root / "config" / "apps.toml").write_text(
        f"""adapter = []

[[app]]
package = "org.aurora.console"
enabled = true
transport = "stdio"
working_dir = "{app_directory}"
command = ["uv", "run", "python", "mcp_server.py"]
timeout_seconds = 30

[[app.tool]]
name = "org.aurora.console.send_message"
result_mode = "terminal"
""",
        encoding="utf-8",
    )

    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)

        class Gateway:
            async def complete(self, request: ModelRequest) -> ModelResult:
                return ModelResult(
                    model="test",
                    negotiated_capabilities=frozenset({"chat", "tools"}),
                    response_mode=request.response_mode,
                    text="",
                    data=None,
                    usage=ModelUsage(),
                    cost_usd=0,
                    tool_calls=(ToolCall("call", "org.aurora.console.send_message", {"text": "来自 bot 的消息"}),),
                    finish_reason="tool_calls",
                )

        runtime.model_gateway = Gateway()
        output: list[str] = []
        try:
            await runtime.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="test:console",
                    summary="来自 bot 的消息",
                    data={"text": "来自 bot 的消息"},
                    source_app="tests",
                    source_instance="console",
                ).to_dict()
            )
            await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            result = await runtime.pump()
            assert result["platform_receipts_emitted"] == 1
            inputs = iter(("/status", "/quit"))
            await run_console(runtime, readline=lambda _prompt: next(inputs), output=output.append)
            assert "bot> 来自 bot 的消息" in output
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
