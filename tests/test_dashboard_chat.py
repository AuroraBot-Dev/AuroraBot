from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.contracts.agent import TaskStatus
from src.contracts.model import ModelRequest, ModelResult, ModelUsage, ToolCall
from src.dashboard.api import create_app
from src.localhost.chat import ChatError
from src.localhost.runtime import AuroraRuntime


class _SequenceGateway:
    def __init__(self, calls: list[ToolCall]) -> None:
        self.calls = calls
        self.requests = []

    async def complete(self, request: ModelRequest) -> ModelResult:
        self.requests.append(request)
        call = self.calls.pop(0)
        return ModelResult(
            model="test",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode=request.response_mode,
            text="",
            data=None,
            usage=ModelUsage(),
            cost_usd=0,
            tool_calls=(call,),
            finish_reason="tool_calls",
        )


class _TextGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResult:
        self.requests.append(request)
        return ModelResult(
            model="test",
            negotiated_capabilities=frozenset({"chat", "tools"}),
            response_mode=request.response_mode,
            text=self.text,
            data=None,
            usage=ModelUsage(),
            cost_usd=0,
            finish_reason="stop",
        )


def _enable_dashboard_reply(project_root: Path) -> None:
    agents_path = project_root / "config" / "agents.toml"
    agents_path.write_text(
        agents_path.read_text(encoding="utf-8").replace(
            'capabilities = ["org.aurora.console.send_message"]',
            'capabilities = ["org.aurora.console.send_message", "org.aurora.dashboard.send_message"]',
        ),
        encoding="utf-8",
    )
    apps_path = project_root / "config" / "apps.toml"
    apps_path.write_text(
        apps_path.read_text(encoding="utf-8")
        + """

[[adapter]]
id = "dashboard.local"
enabled = true
implementation = "src.platform.dashboard:DashboardPlatform"

[[adapter.capability]]
id = "org.aurora.dashboard.send_message"
description = "Publish text to a Dashboard conversation"
result_mode = "terminal"
[adapter.capability.parameters_schema]
type = "object"
required = ["text"]
additionalProperties = false

[adapter.capability.parameters_schema.properties.text]
type = "string"
""",
        encoding="utf-8",
    )


def _register_and_login(client: TestClient, username: str) -> tuple[int, str]:
    registered = client.post("/api/auth/register", json={"username": username, "password": "secret"})
    assert registered.status_code == 200
    logged_in = client.post("/api/auth/login", json={"username": username, "password": "secret"})
    assert logged_in.status_code == 200
    body = logged_in.json()
    return body["user"]["user_id"], body["access_token"]


def test_dashboard_auth_users_and_opaque_session(project_root: Path) -> None:
    with TestClient(create_app(project_root)) as client:
        user_id, token = _register_and_login(client, "alice")
        users = client.get("/api/users", headers={"Authorization": f"Bearer {token}"})

        assert users.status_code == 200, users.text
        bot = next(item for item in users.json()["users"] if item["is_bot"])
        assert bot["username"] == "aurorabot"
        assert bot["online"] is True
        assert client.post("/api/auth/login", json={"username": "aurorabot", "password": "disabled"}).status_code == 401

        assert client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 204
        assert client.get("/api/users", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        assert user_id > 0


def test_websocket_private_message_is_persisted_and_idempotent(project_root: Path) -> None:
    runtime = AuroraRuntime.create(project_root)
    with TestClient(create_app(project_root, runtime=runtime)) as client:
        alice_id, alice_token = _register_and_login(client, "alice")
        bob_id, bob_token = _register_and_login(client, "bob")
        event = {
            "type": "private_message",
            "client_message_id": str(uuid4()),
            "receiver_id": bob_id,
            "message_type": "text",
            "content": "hello",
            "attachment_id": None,
        }
        headers = {"origin": "http://localhost:5173"}
        with client.websocket_connect(f"/ws?token={alice_token}", headers=headers) as alice:
            with client.websocket_connect(f"/ws?token={bob_token}", headers=headers) as bob:
                assert alice.receive_json()["type"] == "presence"
                alice.send_json(event)
                ack = alice.receive_json()
                delivered = bob.receive_json()
                assert ack["type"] == "message_ack"
                assert delivered["message"]["content"] == "hello"

                alice.send_json(event)
                duplicate_ack = alice.receive_json()
                assert duplicate_ack["message_id"] == ack["message_id"]

        history = client.get(
            f"/api/messages/private/{bob_id}",
            headers={"Authorization": f"Bearer {alice_token}"},
        ).json()["messages"]
        assert len(history) == 1
        assert history[0]["sender_id"] == alice_id


def test_websocket_rejects_invalid_json_without_dropping_connection(project_root: Path) -> None:
    with TestClient(create_app(project_root)) as client:
        _user_id, token = _register_and_login(client, "alice")
        headers = {"origin": "http://localhost:5173"}
        with client.websocket_connect(f"/ws?token={token}", headers=headers) as websocket:
            websocket.send_text("{")
            invalid_json = websocket.receive_json()
            assert invalid_json["code"] == "INVALID_PAYLOAD"

            websocket.send_json([])
            invalid_event = websocket.receive_json()
            assert invalid_event["code"] == "INVALID_PAYLOAD"

            websocket.send_json({"type": "ping", "time": 42})
            assert websocket.receive_json() == {"type": "pong", "time": 42}


def test_attachment_upload_is_rejected_at_configured_size_limit(project_root: Path) -> None:
    config = project_root / "config" / "aurora.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("max_upload_bytes = 67108864", "max_upload_bytes = 8"),
        encoding="utf-8",
    )
    with TestClient(create_app(project_root)) as client:
        _user_id, token = _register_and_login(client, "alice")
        response = client.post(
            "/api/attachments",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("large.txt", b"123456789", "text/plain")},
        )

    assert response.status_code == 413
    assert response.headers["X-Aurora-Error"] == "MESSAGE_TOO_LARGE"


def test_bot_text_becomes_amp_and_reply_delivery_is_idempotent(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        await runtime.start()
        try:
            user = await runtime.chat.register("alice", "secret")
            bot = next(item for item in await runtime.chat.list_users(user["user_id"]) if item["is_bot"])
            client_message_id = str(uuid4())
            message = await runtime.chat.send_private_message(
                user["user_id"],
                {
                    "client_message_id": client_message_id,
                    "receiver_id": bot["user_id"],
                    "message_type": "text",
                    "content": "hello bot",
                },
            )
            inbox = tuple(runtime.configuration.runtime.workspace.joinpath("inbox").glob("*.json"))
            assert message["status"] == "saved"
            assert len(inbox) == 1

            session_id = f"dashboard:user:{user['user_id']}"
            first = await runtime.chat.deliver_bot_reply(session_id, "hello human", "effect-1")
            second = await runtime.chat.deliver_bot_reply(session_id, "hello human", "effect-1")
            assert first["message_id"] == second["message_id"]
            history = await runtime.chat.private_history(user["user_id"], bot["user_id"], None, 30)
            assert [item["content"] for item in history] == ["hello bot", "hello human"]
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_failed_dashboard_amp_submission_can_retry_idempotently(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        await runtime.start()
        try:
            user = await runtime.chat.register("alice", "secret")
            bot = next(item for item in await runtime.chat.list_users(user["user_id"]) if item["is_bot"])
            event = {
                "client_message_id": str(uuid4()),
                "receiver_id": bot["user_id"],
                "message_type": "text",
                "content": "retry me",
            }

            async def fail_once(_value: object) -> str:
                raise OSError

            runtime.chat.bind_amp_submitter(fail_once)
            with pytest.raises(ChatError, match="Bot is unavailable"):
                await runtime.chat.send_private_message(user["user_id"], event)

            runtime.chat.bind_amp_submitter(runtime.submit_amp)
            retried = await runtime.chat.send_private_message(user["user_id"], event)
            assert retried["status"] == "saved"
            assert len(tuple(runtime.configuration.runtime.workspace.joinpath("inbox").glob("*.json"))) == 1
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_bot_text_completes_dashboard_effect_and_task(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_dashboard_reply(project_root)
        runtime = AuroraRuntime.create(project_root)
        gateway = _SequenceGateway(
            [ToolCall("call-dashboard", "org.aurora.dashboard.send_message", {"text": "hello human"})]
        )
        runtime.model_gateway = gateway
        await runtime.start()
        try:
            user = await runtime.chat.register("alice", "secret")
            bot = next(item for item in await runtime.chat.list_users(user["user_id"]) if item["is_bot"])
            await runtime.chat.send_private_message(
                user["user_id"],
                {
                    "client_message_id": str(uuid4()),
                    "receiver_id": bot["user_id"],
                    "message_type": "text",
                    "content": "hello bot",
                },
            )

            first = await runtime.pump()
            assert runtime._model_dispatch_task is not None
            await runtime._model_dispatch_task
            second = await runtime.pump()
            third = await runtime.pump()

            assert second["platform_receipts_emitted"] == 1
            assert third["ingested_task_ids"]
            offered_tools = {tool.name for tool in gateway.requests[0].tools}
            assert "org.aurora.dashboard.send_message" in offered_tools
            assert "org.aurora.console.send_message" not in offered_tools
            history = await runtime.chat.private_history(user["user_id"], bot["user_id"], None, 30)
            assert [item["content"] for item in history] == ["hello bot", "hello human"]
            task = runtime.kernel.get_task(first["ingested_task_ids"][0])
            assert task is not None
            assert task.status == TaskStatus.COMPLETED
            assert task.termination_reason == "terminal_effect_succeeded"

            await runtime.pump()
            history = await runtime.chat.private_history(user["user_id"], bot["user_id"], None, 30)
            assert [item["content"] for item in history] == ["hello bot", "hello human"]
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_run_forever_delivers_plain_model_text_to_dashboard(project_root: Path) -> None:
    async def scenario() -> None:
        _enable_dashboard_reply(project_root)
        runtime = AuroraRuntime.create(project_root)
        runtime.model_gateway = _TextGateway("plain provider reply")
        await runtime.start()
        stop = asyncio.Event()
        runner = asyncio.create_task(runtime.run_forever(stop))
        try:
            user = await runtime.chat.register("alice", "secret")
            bot = next(item for item in await runtime.chat.list_users(user["user_id"]) if item["is_bot"])
            await runtime.chat.send_private_message(
                user["user_id"],
                {
                    "client_message_id": str(uuid4()),
                    "receiver_id": bot["user_id"],
                    "message_type": "text",
                    "content": "hello bot",
                },
            )

            async with asyncio.timeout(5):
                while True:
                    history = await runtime.chat.private_history(user["user_id"], bot["user_id"], None, 30)
                    tasks = runtime.kernel.tasks()
                    if len(history) == 2 and tasks and tasks[0].status == TaskStatus.COMPLETED:
                        break
                    await asyncio.sleep(0.02)
            assert [item["content"] for item in history] == ["hello bot", "plain provider reply"]
            assert tasks[0].status == TaskStatus.COMPLETED
        finally:
            stop.set()
            runtime._wake.set()
            await runner
            await runtime.shutdown()

    asyncio.run(scenario())


def test_bot_attachment_is_saved_and_gets_deterministic_reply(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        await runtime.start()
        try:
            user = await runtime.chat.register("alice", "secret")
            bot = next(item for item in await runtime.chat.list_users(user["user_id"]) if item["is_bot"])
            attachment = await runtime.chat.upload_attachment(user["user_id"], "note.txt", "text/plain", b"x")
            await runtime.chat.send_private_message(
                user["user_id"],
                {
                    "client_message_id": str(uuid4()),
                    "receiver_id": bot["user_id"],
                    "message_type": "file",
                    "content": "note.txt",
                    "attachment_id": attachment["attachment_id"],
                },
            )
            history = await runtime.chat.private_history(user["user_id"], bot["user_id"], None, 30)
            assert history[-1]["content"] == "当前暂不支持读取附件。"
            assert not tuple(runtime.configuration.runtime.workspace.joinpath("inbox").glob("*.json"))
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())
