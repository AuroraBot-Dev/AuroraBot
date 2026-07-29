from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from src.contracts.tool import ToolExecutionRequest
from src.platform.console import CONSOLE_SEND_CAPABILITY, CONSOLE_SEND_DESCRIPTOR, ConsolePlatform
from src.platform.console.shell import _PromptReader, run_console
from tests.support import create_test_runtime

if TYPE_CHECKING:
    from pathlib import Path


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
        invalid = await console.execute_tool(
            ToolExecutionRequest("invalid", "session", "other.capability", {"text": "x"})
        )

        assert first.status == duplicate.status == "succeeded"
        assert first.result == duplicate.result
        assert conflict.status == "failed" and "idempotency conflict" in (conflict.error or "")
        assert missing.status == "failed" and missing.error == "interrupted_before_dispatch"
        assert invalid.status == "failed"
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


def test_console_prompt_keeps_session_command_history() -> None:
    reader = _PromptReader(input_stream=DummyInput(), output_stream=DummyOutput())
    reader.session.history.append_string("/status")
    reader.session.history.append_string("/help")
    assert list(reader.session.history.get_strings()) == ["/status", "/help"]


def test_console_input_submits_conversation_and_commands(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        console = ConsolePlatform()
        inputs = iter(("hello", "/pump", "/quit"))
        output: list[str] = []
        try:
            await run_console(runtime, console, readline=lambda _prompt: next(inputs), output=output.append)
            assert any("processed_message_ids" in line for line in output)
            assert any("admitted_task_ids" in line for line in output)
        finally:
            await runtime.shutdown()
            console.close()

    asyncio.run(scenario())
