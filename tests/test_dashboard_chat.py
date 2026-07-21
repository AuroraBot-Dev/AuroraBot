from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from src.contracts.agent import TaskStatus
from src.contracts.amp import new_amp
from src.contracts.model import ModelRequest, ModelResult, ModelUsage, ToolCall
from src.localhost.ports import ToolExecutionRequest, ToolExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.dashboard import (
    DASHBOARD_SEND_CAPABILITY,
    DASHBOARD_SEND_DESCRIPTOR,
    ChatError,
    ChatService,
    DashboardPlatform,
)

if TYPE_CHECKING:
    from pathlib import Path

_EXPECTED_TOOL_CALLS = 2


async def _started_chat(runtime: AuroraRuntime) -> ChatService:
    chat = ChatService(runtime.configuration.dashboard, runtime)
    await chat.start()
    return chat


async def _owner(chat: ChatService) -> dict[str, object]:
    row = await asyncio.to_thread(chat.store.fetch_one, "SELECT * FROM users WHERE id = ?", (chat.owner_id,))
    assert row is not None
    return chat._user(row)


def _tool(request_id: str, text: str) -> ToolExecutionRequest:
    return ToolExecutionRequest(request_id, "any:session", DASHBOARD_SEND_CAPABILITY, {"text": text})


def test_dashboard_tool_has_uniform_three_field_descriptor() -> None:
    assert DASHBOARD_SEND_CAPABILITY == "org.aurora.dashboard.send"
    assert set(DASHBOARD_SEND_DESCRIPTOR.to_dict()) == {"id", "description", "parameters_schema"}
    assert set(DASHBOARD_SEND_DESCRIPTOR.parameters_schema["properties"]) == {"text"}


def test_dashboard_tool_uses_fixed_owner_and_is_recoverable(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        chat = await _started_chat(runtime)
        platform = DashboardPlatform(chat)
        owner = await _owner(chat)
        bot = next(item for item in await chat.list_users(int(owner["user_id"])) if item["is_bot"])
        request = _tool("dashboard-1", "hello owner")
        queue = await chat.subscribe(int(owner["user_id"]))
        try:
            first = await platform.execute_tool(request)
            duplicate = await platform.execute_tool(request)
            conflict = await platform.execute_tool(replace(request, parameters={"text": "different"}))
            recovered = await platform.recover_tool(request)
            missing = await platform.recover_tool(_tool("missing", "missing"))

            assert first.status == duplicate.status == recovered.status == "succeeded"
            assert first.result == duplicate.result == recovered.result
            assert conflict.status == "failed" and conflict.error == "request_id_reused_with_different_content"
            assert missing.status == "failed" and missing.error == "interrupted_before_dispatch"
            pushed = queue.get_nowait()
            assert pushed["message"]["receiver_id"] == owner["user_id"]
            assert queue.empty()
            history = await chat.private_history(int(owner["user_id"]), int(bot["user_id"]), None, 30)
            assert [item["content"] for item in history] == ["hello owner"]
        finally:
            await chat.unsubscribe(int(owner["user_id"]), queue)
            await runtime.shutdown()

    asyncio.run(scenario())


def test_only_configured_owner_can_trigger_bot_and_attachments_are_rejected(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        chat = await _started_chat(runtime)
        try:
            owner = await _owner(chat)
            bot = next(item for item in await chat.list_users(int(owner["user_id"])) if item["is_bot"])
            now = datetime.now(UTC).isoformat()
            bob_id = await asyncio.to_thread(
                chat.store.execute,
                "INSERT INTO users(username, password_hash, display_name, is_bot, is_owner, created_at, updated_at) "
                "VALUES ('bob', 'disabled', 'Bob', 0, 0, ?, ?)",
                (now, now),
            )
            with pytest.raises(ChatError) as non_owner:
                await chat.send_private_message(
                    bob_id,
                    {
                        "client_message_id": str(uuid4()),
                        "receiver_id": bot["user_id"],
                        "message_type": "text",
                        "content": "forged",
                    },
                )
            assert non_owner.value.code == "BOT_OWNER_ONLY"

            attachment = await chat.upload_attachment(int(owner["user_id"]), "note.txt", "text/plain", b"x")
            with pytest.raises(ChatError) as unsupported:
                await chat.send_private_message(
                    int(owner["user_id"]),
                    {
                        "client_message_id": str(uuid4()),
                        "receiver_id": bot["user_id"],
                        "message_type": "file",
                        "content": "note.txt",
                        "attachment_id": attachment["attachment_id"],
                    },
                )
            assert unsupported.value.code == "BOT_ATTACHMENT_UNSUPPORTED"
            assert runtime.kernel.tasks() == ()
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_dashboard_owner_input_amp_has_only_source_session_and_useful_data(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        chat = await _started_chat(runtime)
        try:
            owner = await _owner(chat)
            bot = next(item for item in await chat.list_users(int(owner["user_id"])) if item["is_bot"])
            client_message_id = str(uuid4())
            await chat.send_private_message(
                int(owner["user_id"]),
                {
                    "client_message_id": client_message_id,
                    "receiver_id": bot["user_id"],
                    "message_type": "text",
                    "content": "hello bot",
                },
            )
            inbox = tuple(runtime.configuration.runtime.workspace.joinpath("inbox").glob("*.json"))
            assert len(inbox) == 1
            amp = json.loads(inbox[0].read_text(encoding="utf-8"))
            assert amp["payload"]["session_id"] == "dashboard:owner"
            assert amp["payload"]["data"] == {
                "chat_message_id": client_message_id,
                "channel": "owner_bot_chat",
                "text": "hello bot",
            }
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_console_input_can_call_dashboard_tool_twice_then_complete(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root, tool_bindings=None)
        chat = await _started_chat(runtime)
        platform = DashboardPlatform(chat)
        runtime.bind_tool_executors(
            (
                ToolExecutorBinding(
                    DASHBOARD_SEND_DESCRIPTOR,
                    platform,
                    "platform.dashboard",
                    "local",
                    platform,
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
                            f"dashboard-call-{self.calls}",
                            DASHBOARD_SEND_CAPABILITY,
                            {
                                "text": f"dashboard {self.calls}",
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
                    summary="send to dashboard twice",
                    data={"text": "send to dashboard twice", "channel": "local_console"},
                    source_app="platform.console",
                    source_instance="default",
                ).to_dict()
            )
            first = await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            assert (await runtime.pump())["tool_receipts_emitted"] == 1
            await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            assert (await runtime.pump())["tool_receipts_emitted"] == 1
            await runtime.pump()

            owner = await _owner(chat)
            bot = next(item for item in await chat.list_users(int(owner["user_id"])) if item["is_bot"])
            history = await chat.private_history(int(owner["user_id"]), int(bot["user_id"]), None, 30)
            assert [item["content"] for item in history] == ["dashboard 1", "dashboard 2"]
            task = runtime.kernel.get_task(first["ingested_task_ids"][0])
            assert task is not None and task.status == TaskStatus.COMPLETED
            assert task.tool_calls == _EXPECTED_TOOL_CALLS
            assert DASHBOARD_SEND_CAPABILITY in {tool.name for tool in gateway.requests[0].tools}
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
