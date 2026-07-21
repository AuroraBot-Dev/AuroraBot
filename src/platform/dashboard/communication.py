"""Dashboard owner ingress and fixed-target Tool delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.localhost.command_types import CommandControl
from src.localhost.ports import ToolExecutionRequest, ToolOutcome
from src.platform.dashboard.adapter import DASHBOARD_SEND_CAPABILITY
from src.platform.dashboard.routing import (
    PrivateMessageInput,
    command_reply_id,
    dashboard_input,
    is_conversation_command,
    is_quit_command,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Awaitable, Callable

    from src.contracts.configuration import DashboardConfig
    from src.localhost.ports import InteractiveInputPort
    from src.platform.dashboard.store import ChatStore

    Publish = Callable[[int, dict[str, Any]], Awaitable[None]]


class ChatError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class DashboardCommunication:
    """Keep Dashboard user IDs and durable delivery state inside the Platform boundary."""

    def __init__(
        self,
        configuration: DashboardConfig,
        store: ChatStore,
        input_port: InteractiveInputPort,
        bot_id: Callable[[], int],
        publish: Publish,
    ) -> None:
        self._configuration = configuration
        self._store = store
        self._input_port = input_port
        self._bot_id = bot_id
        self._publish = publish

    async def require_owner(self, user_id: int) -> None:
        owner = await asyncio.to_thread(
            self._store.fetch_one,
            "SELECT id FROM users WHERE id = ? AND username = ? AND is_owner = 1 AND is_bot = 0",
            (user_id, self._configuration.owner_username),
        )
        if owner is None:
            raise ChatError("BOT_OWNER_ONLY", "Only the configured Dashboard owner can message the Bot", 403)

    async def handle_bot_input(
        self,
        sender_id: int,
        row_id: int,
        parsed: PrivateMessageInput,
        message: dict[str, Any],
        *,
        created: bool,
    ) -> None:
        if parsed.message_type != "text":
            raise ChatError("BOT_ATTACHMENT_UNSUPPORTED", "Bot does not accept attachments")
        content = parsed.content or ""
        is_command = content.lstrip().startswith("/")
        if not created and is_command and not is_conversation_command(content):
            return
        try:
            routed = await self._input_port.route_input(dashboard_input(parsed))
            reply = await self._persist_command_reply(
                sender_id,
                parsed.client_message_id,
                routed.text,
                publish_reply=routed.publish_reply,
            )
            await asyncio.to_thread(
                self._store.execute,
                "UPDATE messages SET status = 'saved', amp_message_id = ? WHERE id = ?",
                (routed.message_id, row_id),
            )
            message["status"] = "saved"
            if reply is not None:
                message["_post_ack"] = {"reply": reply, "control": routed.control}
        except ChatError:
            raise
        except Exception as error:
            await asyncio.to_thread(
                self._store.execute,
                "UPDATE messages SET status = 'failed' WHERE id = ?",
                (row_id,),
            )
            raise ChatError("BOT_UNAVAILABLE", "Bot is unavailable", 503) from error

    async def attach_existing_command_reply(
        self,
        message: dict[str, Any],
        receiver_id: int,
        source_client_message_id: str,
        content: str,
    ) -> None:
        reply_client_id = command_reply_id(receiver_id, source_client_message_id)
        row = await asyncio.to_thread(
            self._store.fetch_one,
            "SELECT id FROM messages WHERE sender_id = ? AND client_message_id = ?",
            (self._bot_id(), reply_client_id),
        )
        if row is None:
            return
        message_row = await asyncio.to_thread(self._store.message_with_attachment, int(row["id"]))
        assert message_row is not None
        control = CommandControl.SHUTDOWN_PROCESS if is_quit_command(content) else CommandControl.NONE
        message["_post_ack"] = {"reply": self._message(message_row), "control": control}

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        existing = await asyncio.to_thread(
            self._store.fetch_one, "SELECT * FROM dashboard_tool_requests WHERE request_id = ?", (request.request_id,)
        )
        if existing is not None:
            return self._tool_outcome(existing, request)

        error = self._validate_tool(request)
        text = request.parameters.get("text")
        now = await asyncio.to_thread(self._now)
        await asyncio.to_thread(
            self._store.execute,
            "INSERT INTO dashboard_tool_requests(request_id, request_digest, text, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'dispatch_started', ?, ?)",
            (request.request_id, _request_digest(request), text if isinstance(text, str) else "", now, now),
        )
        if error is not None:
            return await self._finish_failure(request.request_id, error)

        owner = await asyncio.to_thread(
            self._store.fetch_one,
            "SELECT id FROM users WHERE username = ? AND is_owner = 1 AND is_bot = 0",
            (self._configuration.owner_username,),
        )
        if owner is None:
            return await self._finish_failure(request.request_id, "configured Dashboard owner is unavailable")
        owner_id = int(owner["id"])
        message_id = str(uuid5(NAMESPACE_URL, f"aurora-dashboard-tool:{request.request_id}"))
        message_row, created = await asyncio.to_thread(
            self._store.create_message,
            client_message_id=message_id,
            sender_id=self._bot_id(),
            receiver_id=owner_id,
            message_type="text",
            content=str(text),
            attachment_id=None,
            source_tool_request_id=request.request_id,
        )
        summary = "Dashboard message sent"
        await asyncio.to_thread(
            self._store.execute,
            "UPDATE dashboard_tool_requests SET status = 'succeeded', summary = ?, external_message_id = ?, "
            "updated_at = ? WHERE request_id = ?",
            (summary, message_id, await asyncio.to_thread(self._now), request.request_id),
        )
        if created:
            await self._publish(owner_id, {"type": "private_message", "message": self._message(message_row)})
        return ToolOutcome("succeeded", summary, result={"message_id": message_id})

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        row = await asyncio.to_thread(
            self._store.fetch_one, "SELECT * FROM dashboard_tool_requests WHERE request_id = ?", (request.request_id,)
        )
        if row is None:
            return ToolOutcome(
                "failed", "Dashboard send was interrupted before dispatch", error="interrupted_before_dispatch"
            )
        return self._tool_outcome(row, request)

    @staticmethod
    def _validate_tool(request: ToolExecutionRequest) -> str | None:
        if request.capability != DASHBOARD_SEND_CAPABILITY:
            return f"unsupported Dashboard capability: {request.capability}"
        if set(request.parameters) != {"text"}:
            return "Dashboard send parameters must contain only text"
        text = request.parameters.get("text")
        if not isinstance(text, str) or not text.strip():
            return "Dashboard send text must be a non-empty string"
        return None

    async def _finish_failure(self, request_id: str, error: str) -> ToolOutcome:
        summary = "Dashboard send failed"
        await asyncio.to_thread(
            self._store.execute,
            "UPDATE dashboard_tool_requests SET status = 'failed', summary = ?, error = ?, updated_at = ? "
            "WHERE request_id = ?",
            (summary, error, await asyncio.to_thread(self._now), request_id),
        )
        return ToolOutcome("failed", summary, error=error)

    @staticmethod
    def _tool_outcome(row: sqlite3.Row, request: ToolExecutionRequest) -> ToolOutcome:
        digest = row["request_digest"]
        if digest is None:
            return ToolOutcome("unknown", "Dashboard send identity is unknown", error="legacy_request_identity_unknown")
        if str(digest) != _request_digest(request):
            return ToolOutcome(
                "failed", "Dashboard Tool idempotency conflict", error="request_id_reused_with_different_content"
            )
        status = str(row["status"])
        if status == "dispatch_started":
            return ToolOutcome(
                "unknown", "Dashboard message delivery is unknown", error="dispatch_started_without_terminal_outcome"
            )
        if status == "succeeded":
            return ToolOutcome("succeeded", str(row["summary"]), result={"message_id": str(row["external_message_id"])})
        return ToolOutcome("failed", str(row["summary"]), error=str(row["error"]))

    async def _persist_command_reply(
        self,
        receiver_id: int,
        source_client_message_id: str,
        text: str | None,
        *,
        publish_reply: bool,
    ) -> dict[str, Any] | None:
        if not publish_reply or text is None:
            return None
        row, _created = await asyncio.to_thread(
            self._store.create_message,
            client_message_id=command_reply_id(receiver_id, source_client_message_id),
            sender_id=self._bot_id(),
            receiver_id=receiver_id,
            message_type="text",
            content=text,
            attachment_id=None,
        )
        return self._message(row)

    @staticmethod
    def _message(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": int(row["id"]),
            "client_message_id": str(row["client_message_id"]),
            "sender_id": int(row["sender_id"]),
            "receiver_id": int(row["receiver_id"]),
            "message_type": str(row["message_type"]),
            "content": row["content"],
            "attachment": None,
            "created_at": str(row["created_at"]),
            "status": str(row["status"]),
        }

    @staticmethod
    def _now() -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()


def _request_digest(request: ToolExecutionRequest) -> str:
    canonical = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
