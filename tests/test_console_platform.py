from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.contracts.amp import new_amp
from src.contracts.model import ModelRequest, ModelResult, ModelUsage, ToolCall
from src.localhost.ports import EffectExecutionRequest, EffectExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.console import CONSOLE_SEND_CAPABILITY, CONSOLE_SEND_DESCRIPTOR, ConsolePlatform
from src.platform.console.shell import run_console

if TYPE_CHECKING:
    from pathlib import Path


def test_console_platform_owns_successful_effect_output() -> None:
    async def scenario() -> None:
        console = ConsolePlatform()
        first = await console.execute_effect(
            EffectExecutionRequest("request-1", "session", CONSOLE_SEND_CAPABILITY, {"text": "one"})
        )
        second = await console.execute_effect(
            EffectExecutionRequest("request-2", "session", CONSOLE_SEND_CAPABILITY, {"text": "two"})
        )

        assert first.succeeded is True
        assert second.succeeded is True
        assert await console.next_message() == "one"
        assert console.drain_messages() == ("two",)

    asyncio.run(scenario())


def test_console_executor_delivers_text_to_the_interactive_shell(project_root: Path) -> None:
    async def scenario() -> None:
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
                    tool_calls=(ToolCall("call", CONSOLE_SEND_CAPABILITY, {"text": "来自 bot 的消息"}),),
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
            assert result["effect_receipts_emitted"] == 1
            inputs = iter(("/status", "/quit"))
            await run_console(runtime, console, readline=lambda _prompt: next(inputs), output=output.append)
            assert "Bot> 来自 bot 的消息" in output
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
