from __future__ import annotations

import asyncio
from pathlib import Path

from src.kernel.events import new_amp
from src.localhost.runtime import AuroraRuntime
from src.localhost.shell import run_console


def test_console_mcp_tool_delivers_text_to_the_interactive_shell(project_root: Path) -> None:
    source_root = Path(__file__).parents[1]
    app_directory = (source_root / "src" / "apps" / "aurora-app-console").as_posix()
    (project_root / "config" / "apps.toml").write_text(
        f"""adapter = []

[[app]]
package = "im.polaris.console"
enabled = true
transport = "stdio"
working_dir = "{app_directory}"
command = ["uv", "run", "python", "mcp_server.py"]
timeout_seconds = 30
allowed_tools = ["im.polaris.console.send_message"]
""",
        encoding="utf-8",
    )

    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
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
            result = await runtime.run_cycle()
            assert result["platform_receipts_emitted"] == 1
            inputs = iter(("/status", "/quit"))
            await run_console(runtime, readline=lambda _prompt: next(inputs), output=output.append)
            assert "bot> 来自 bot 的消息" in output
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
