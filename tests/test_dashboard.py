# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.contracts.tool import ToolExecutionRequest
from src.localhost.api import create_debug_app
from src.platform.dashboard import (
    DASHBOARD_SEND_CAPABILITY,
    DASHBOARD_SEND_DESCRIPTOR,
    ChatError,
    ChatService,
    DashboardPlatform,
    _create,
    _open_browser_when_ready,
)
from tests.support import create_test_runtime
from tests.test_events import valid_amp

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.configuration import DashboardConfig
    from src.localhost.runtime import AuroraRuntime
    from src.utils.uvicorn import SignalSafeServer


async def _started_chat(runtime: AuroraRuntime) -> ChatService:
    chat = ChatService(runtime.configuration.dashboard, runtime)
    await chat.start()
    return chat


async def _owner(chat: ChatService) -> dict[str, object]:
    row = await asyncio.to_thread(chat.store.fetch_one, "SELECT * FROM users WHERE id = ?", (chat.owner_id,))
    assert row is not None
    return chat._user(row)


def _user_id(user: dict[str, object]) -> int:
    value = user["user_id"]
    assert isinstance(value, int)
    return value


def _tool(request_id: str, text: str) -> ToolExecutionRequest:
    return ToolExecutionRequest(request_id, "any:session", DASHBOARD_SEND_CAPABILITY, {"text": text})


def test_dashboard_tool_descriptor_and_recovery(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        chat = await _started_chat(runtime)
        platform = DashboardPlatform(chat)
        owner = await _owner(chat)
        owner_id = _user_id(owner)
        bot = next(item for item in await chat.list_users(owner_id) if item["is_bot"])
        bot_id = _user_id(bot)
        request = _tool("dashboard-1", "hello owner")
        queue = await chat.subscribe(owner_id)
        try:
            first = await platform.execute_tool(request)
            duplicate = await platform.execute_tool(request)
            conflict = await platform.execute_tool(replace(request, parameters={"text": "different"}))
            await asyncio.to_thread(
                chat.store.execute,
                "UPDATE dashboard_tool_requests SET status = 'dispatch_started', summary = NULL, "
                "external_message_id = NULL WHERE request_id = ?",
                (request.request_id,),
            )
            recovered = await platform.recover_tool(request)
            missing = await platform.recover_tool(_tool("missing", "missing"))

            assert first.status == duplicate.status == recovered.status == "succeeded"
            assert first.result == duplicate.result == recovered.result
            assert conflict.status == "failed" and conflict.error == "request_id_reused_with_different_content"
            assert missing.status == "failed" and missing.error == "interrupted_before_dispatch"
            pushed = queue.get_nowait()
            assert pushed["message"]["receiver_id"] == owner["user_id"]
            history = await chat.private_history(owner_id, bot_id, None, 30)
            assert [item["content"] for item in history] == ["hello owner"]
        finally:
            await chat.unsubscribe(owner_id, queue)
            await runtime.shutdown()

    assert DASHBOARD_SEND_CAPABILITY == "org.aurora.dashboard.send"
    assert set(DASHBOARD_SEND_DESCRIPTOR.to_dict()) == {
        "id",
        "description",
        "parameters_schema",
        "runtime_completion",
    }
    asyncio.run(scenario())


def test_only_owner_can_trigger_bot_and_attachments_are_rejected(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        handle = await _create(runtime.configuration, runtime)
        platform = cast("DashboardPlatform", handle.bindings[0].executor)
        chat = platform._chat
        try:
            token_path = runtime.configuration.dashboard.database_path.parent / "Token.txt"
            assert token_path.stat().st_mode & 0o777 == 0o600
            owner = await _owner(chat)
            owner_id = _user_id(owner)
            bot = next(item for item in await chat.list_users(owner_id) if item["is_bot"])
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

            attachment = await chat.upload_attachment(owner_id, "note.txt", "text/plain", b"x")
            with pytest.raises(ChatError) as unsupported:
                await chat.send_private_message(
                    owner_id,
                    {
                        "client_message_id": str(uuid4()),
                        "receiver_id": bot["user_id"],
                        "message_type": "file",
                        "content": "note.txt",
                        "attachment_id": attachment["attachment_id"],
                    },
                )
            assert unsupported.value.code == "BOT_ATTACHMENT_UNSUPPORTED"
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_dashboard_owner_input_is_idempotent_amp(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        handle = await _create(runtime.configuration, runtime)
        platform = cast("DashboardPlatform", handle.bindings[0].executor)
        chat = platform._chat
        try:
            owner = await _owner(chat)
            owner_id = _user_id(owner)
            bot = next(item for item in await chat.list_users(owner_id) if item["is_bot"])
            client_message_id = str(uuid4())
            payload = {
                "client_message_id": client_message_id,
                "receiver_id": bot["user_id"],
                "message_type": "text",
                "content": "hello bot",
            }
            first = await chat.send_private_message(owner_id, payload)
            duplicate = await chat.send_private_message(owner_id, payload)
            result = await runtime.pump()
            assert first == duplicate
            assert len(result["admitted_task_ids"]) == 1
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_independent_localhost_debug_app_drives_and_queries_engine(project_root: Path) -> None:
    runtime = create_test_runtime(project_root)
    app = create_debug_app(runtime)
    with TestClient(app) as client:  # pyright: ignore[reportArgumentType]
        assert client.get("/healthz").status_code == 404
        assert client.post("/v1/debug/amp", json={}).status_code == 422
        assert client.post("/v1/debug/pump?max_turns=0").status_code == 422
        submitted = client.post("/v1/debug/amp", json=valid_amp())
        assert submitted.status_code == 202
        first = client.post("/v1/debug/pump?max_turns=1").json()
        task_id = first["admitted_task_ids"][0]
        task = client.get(f"/v1/debug/tasks/{task_id}")
        assert task.status_code == 200
        agent_id = task.json()["task"]["root_agent_id"]
        assert client.get(f"/v1/debug/agents/{agent_id}").status_code == 200
        assert client.get("/v1/debug/agents/missing").status_code == 404
        assert client.get("/v1/debug/tasks/missing").status_code == 404
        assert client.get("/v1/debug/brain-context").status_code == 200
        assert client.get("/v1/debug/status").status_code == 200
    asyncio.run(runtime.shutdown())


def test_browser_opens_once_server_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """浏览器在 server 就绪后打开一次，地址按 Dashboard 配置格式化。"""
    opened: list[str] = []
    opened_event = threading.Event()

    def record_open(url: str) -> None:
        opened.append(url)
        opened_event.set()

    monkeypatch.setattr("src.platform.dashboard.webbrowser.open", record_open)

    class FakeServer:
        def __init__(self) -> None:
            self.started = False
            self.should_exit = False

    async def scenario() -> None:
        server = cast("SignalSafeServer", FakeServer())
        stop = asyncio.Event()
        task = asyncio.create_task(
            _open_browser_when_ready(server, cast("DashboardConfig", SimpleNamespace(host="::", port=8000)), stop)
        )
        await asyncio.sleep(0.05)
        assert opened == []
        server.started = True
        assert await asyncio.to_thread(opened_event.wait, 1)
        assert not task.done()
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
    assert opened == ["http://127.0.0.1:8000"]


def test_browser_aborts_when_server_stops_before_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """server 在就绪前停止时不再打开浏览器。"""
    opened: list[str] = []
    monkeypatch.setattr("src.platform.dashboard.webbrowser.open", opened.append)

    class FakeServer:
        def __init__(self) -> None:
            self.started = False
            self.should_exit = True

    asyncio.run(
        _open_browser_when_ready(
            cast("SignalSafeServer", FakeServer()),
            cast("DashboardConfig", SimpleNamespace(host="127.0.0.1", port=8000)),
            asyncio.Event(),
        )
    )
    assert opened == []
