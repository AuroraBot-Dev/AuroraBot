from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING

from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from src.contracts.agent import TaskStatus
from src.contracts.amp import new_amp
from src.contracts.model import ModelRequest, ModelResult, ModelUsage, ToolCall
from src.localhost.ports import ToolExecutionRequest, ToolExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.console import CONSOLE_SEND_CAPABILITY, CONSOLE_SEND_DESCRIPTOR, ConsolePlatform
from src.platform.console.shell import _PromptReader, run_console

if TYPE_CHECKING:
    from pathlib import Path

_EXPECTED_TOOL_CALLS = 2


def _tool(request_id: str, text: str) -> ToolExecutionRequest:
    return ToolExecutionRequest(request_id, "local:console", CONSOLE_SEND_CAPABILITY, {"text": text})


def test_console_tool_is_idempotent_and_recoverable(tmp_path: Path) -> None:
    async def scenario() -> None:
        ledger = tmp_path / "console.sqlite3"
        console = ConsolePlatform(ledger)
        request = _tool("request-1", "one")

        first = await console.execute_tool(request)
        duplicate = await console.execute_tool(request)
        conflict = await console.execute_tool(replace(request, parameters={"text": "different"}))
        missing = await console.recover_tool(_tool("missing", "two"))

        assert first.status == duplicate.status == "succeeded"
        assert first.result == duplicate.result
        assert conflict.status == "failed" and "idempotency conflict" in (conflict.error or "")
        assert missing.status == "failed" and missing.error == "interrupted_before_dispatch"
        assert await console.next_message() == "one"
        console.close()

        restarted = ConsolePlatform(ledger)
        assert (await restarted.recover_tool(request)).status == "succeeded"
        assert restarted.drain_messages() == ()
        restarted.close()

    asyncio.run(scenario())


def test_console_tool_has_uniform_three_field_descriptor() -> None:
    assert CONSOLE_SEND_CAPABILITY == "org.aurora.console.send"
    assert set(CONSOLE_SEND_DESCRIPTOR.to_dict()) == {"id", "description", "parameters_schema"}
    assert set(CONSOLE_SEND_DESCRIPTOR.parameters_schema["properties"]) == {"text"}


def test_console_input_amp_contains_local_channel_data(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        console = ConsolePlatform()
        inputs = iter(("hello", "/quit"))
        try:
            await run_console(runtime, console, readline=lambda _prompt: next(inputs), output=lambda _text: None)
            inbox = tuple(runtime.configuration.runtime.workspace.joinpath("inbox").glob("*.json"))
            assert len(inbox) == 1
            amp = json.loads(inbox[0].read_text(encoding="utf-8"))
            assert amp["payload"]["session_id"] == "local:console"
            assert amp["payload"]["data"] == {"channel": "local_console", "text": "hello"}
        finally:
            await runtime.shutdown()
            console.close()

    asyncio.run(scenario())


def test_console_prompt_keeps_session_command_history() -> None:
    reader = _PromptReader(input_stream=DummyInput(), output_stream=DummyOutput())
    reader.session.history.append_string("/status")
    reader.session.history.append_string("/help")
    assert list(reader.session.history.get_strings()) == ["/status", "/help"]


def test_console_tool_runs_twice_with_explicit_task_completion(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root, tool_bindings=None)
        console = ConsolePlatform()
        runtime.bind_tool_executors(
            (
                ToolExecutorBinding(
                    CONSOLE_SEND_DESCRIPTOR,
                    console,
                    "platform.console",
                    "test",
                    console,
                ),
            )
        )

        class Gateway:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[ModelRequest] = []

            async def complete(self, request: ModelRequest) -> ModelResult:
                self.calls += 1
                self.requests.append(request)
                return ModelResult(
                    model="test",
                    negotiated_capabilities=frozenset({"chat", "tools"}),
                    response_mode=request.response_mode,
                    text="",
                    data=None,
                    usage=ModelUsage(),
                    cost_usd=0,
                    tool_calls=(
                        ToolCall(
                            f"call-{self.calls}",
                            CONSOLE_SEND_CAPABILITY,
                            {
                                "text": f"message {self.calls}",
                                "complete_task": self.calls == _EXPECTED_TOOL_CALLS,
                            },
                        ),
                    ),
                    finish_reason="tool_calls",
                )

        gateway = Gateway()
        runtime.model_gateway = gateway
        try:
            await runtime.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="local:console",
                    summary="send twice",
                    data={"text": "send twice", "channel": "local_console"},
                    source_app="platform.console",
                    source_instance="default",
                ).to_dict()
            )
            await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            assert (await runtime.pump())["tool_receipts_emitted"] == 1
            await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            assert (await runtime.pump())["tool_receipts_emitted"] == 1
            await runtime.pump()

            assert console.drain_messages() == ("message 1", "message 2")
            assert runtime.kernel.tasks()[0].status == TaskStatus.COMPLETED
            assert runtime.kernel.tasks()[0].tool_calls == _EXPECTED_TOOL_CALLS
            descriptor = next(tool for tool in gateway.requests[0].tools if tool.name == CONSOLE_SEND_CAPABILITY)
            assert descriptor.parameters_schema["properties"]["complete_task"]["type"] == "boolean"
        finally:
            await runtime.shutdown()
            console.close()

    asyncio.run(scenario())
