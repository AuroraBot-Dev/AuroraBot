from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from src.contracts.agent import TaskStatus
from src.contracts.amp import new_amp
from src.contracts.model import ModelRequest, ModelResult, ModelUsage, ToolCall
from src.localhost.ports import PublicationExecutionRequest, PublicationExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.console import (
    CONSOLE_AUDIENCE,
    CONSOLE_ENDPOINT,
    CONSOLE_SEND_CAPABILITY,
    CONSOLE_SEND_DESCRIPTOR,
    ConsolePlatform,
)
from src.platform.console.shell import _PromptReader, run_console

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_PUBLICATIONS = 2


def _publication(request_id: str, route_ref: str, text: str) -> PublicationExecutionRequest:
    return PublicationExecutionRequest(
        request_id=request_id,
        capability=CONSOLE_SEND_CAPABILITY,
        endpoint_id=CONSOLE_ENDPOINT,
        operation="reply",
        text=text,
        source_audience_ref=CONSOLE_AUDIENCE,
        target_audience_ref=CONSOLE_AUDIENCE,
        root_message_id="root",
        route_ref=route_ref,
    )


def test_console_publication_is_idempotent_and_recoverable(tmp_path: Path) -> None:
    async def scenario() -> None:
        ledger = tmp_path / "console.sqlite3"
        console = ConsolePlatform(ledger)
        console.register_reply_route("route", "event")
        request = _publication("request-1", "route", "one")
        first = await console.execute_publication(request)
        duplicate = await console.execute_publication(request)
        missing = await console.recover_publication(_publication("missing", "route", "two"))

        assert first.status == duplicate.status == "accepted"
        assert first.external_message_id == duplicate.external_message_id
        assert missing.status == "failed" and missing.error == "interrupted_before_dispatch"
        assert await console.next_message() == "one"
        assert console.drain_messages() == ()
        console.close()

        restarted = ConsolePlatform(ledger)
        recovered = await restarted.recover_publication(request)
        assert recovered.status == "accepted"
        assert recovered.external_message_id == first.external_message_id
        assert restarted.drain_messages() == ()
        restarted.close()

    asyncio.run(scenario())


def test_console_prompt_keeps_session_command_history() -> None:
    reader = _PromptReader(input_stream=DummyInput(), output_stream=DummyOutput())

    reader.session.history.append_string("/status")
    reader.session.history.append_string("/help")

    assert list(reader.session.history.get_strings()) == ["/status", "/help"]


def test_console_publication_delivers_two_replies_then_completes_task(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root, executor_bindings=None, publication_bindings=None)
        console = ConsolePlatform()
        runtime.bind_platform_executors(
            (),
            (
                PublicationExecutorBinding(
                    CONSOLE_SEND_DESCRIPTOR,
                    console,
                    console,
                    "platform.console",
                    "test",
                ),
            ),
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
                                "text": "第一条" if self.calls == 1 else "第二条",
                                "complete_task": self.calls == EXPECTED_PUBLICATIONS,
                            },
                        ),
                    ),
                    finish_reason="tool_calls",
                )

        gateway = Gateway()
        runtime.model_gateway = gateway
        output: list[str] = []
        external_event_id = str(uuid4())
        route_ref = str(uuid4())
        console.register_reply_route(route_ref, external_event_id)
        try:
            await runtime.submit_amp(
                new_amp(
                    event_type="message.received",
                    session_id="test:console",
                    summary="请回复两次",
                    data={
                        "text": "请回复两次",
                        "communication": {
                            "endpoint_id": CONSOLE_ENDPOINT,
                            "external_event_id": external_event_id,
                            "external_message_id": str(uuid4()),
                            "conversation_ref": "console.local:owner",
                            "actor_ref": "owner.local",
                            "audience_ref": CONSOLE_AUDIENCE,
                            "reply_route_ref": route_ref,
                        },
                    },
                    source_app="tests",
                    source_instance="console",
                ).to_dict()
            )
            await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            first = await runtime.pump()
            assert first["publication_receipts_emitted"] == 1
            await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            second = await runtime.pump()
            assert second["publication_receipts_emitted"] == 1
            completed = await runtime.pump()
            assert completed["ingested_task_ids"]
            assert runtime.kernel.tasks()[0].status == TaskStatus.COMPLETED
            assert runtime.kernel.tasks()[0].tool_calls == EXPECTED_PUBLICATIONS
            reply_tool = next(tool for tool in gateway.requests[0].tools if tool.name == CONSOLE_SEND_CAPABILITY)
            assert reply_tool.parameters_schema["properties"]["complete_task"]["type"] == "boolean"
            inputs = iter(("/cls", "/status", "/quit"))
            await run_console(
                runtime,
                console,
                readline=lambda _prompt: next(inputs),
                output=output.append,
            )
            assert "Bot> 第一条" in output
            assert "Bot> 第二条" in output
            assert "\033[2J\033[H" in output
        finally:
            await runtime.shutdown()
            console.close()

    asyncio.run(scenario())
