"""Dashboard owner ingress, private reply routes, and Publication delivery."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.localhost.command_types import CommandControl
from src.localhost.ports import PublicationExecutionRequest, PublicationOutcome
from src.platform.dashboard.adapter import (
    DASHBOARD_AUDIENCE,
    DASHBOARD_ENDPOINT,
    DASHBOARD_REPLY_CAPABILITY,
)
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
    """Keep Dashboard user IDs and delivery state inside the Platform boundary."""

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
            "SELECT id FROM users WHERE id = ? AND username = ? AND is_bot = 0",
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
            await self._direct_reply(sender_id, "当前暂不支持读取附件。", f"attachment-unsupported:{row_id}")
            return
        content = parsed.content or ""
        is_command = content.lstrip().startswith("/")
        if not created and is_command and not is_conversation_command(content):
            return
        try:
            communication = await self._register_context(sender_id, parsed.client_message_id)
            routed = await self._input_port.route_input(dashboard_input(parsed, communication))
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

    async def execute_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        existing = await asyncio.to_thread(self._store.fetch_one, self._publication_query(), (request.request_id,))
        if existing is not None:
            return self._publication_outcome(existing, request)

        route, error = await self._validate_publication(request)
        row, created = await asyncio.to_thread(
            self._store.start_publication,
            request_id=request.request_id,
            route_ref=request.route_ref,
            capability=request.capability,
            endpoint_id=request.endpoint_id,
            operation=request.operation,
            text=request.text,
        )
        if not created:
            return self._publication_outcome(row, request)
        if error is not None:
            summary = "Dashboard reply failed"
            await asyncio.to_thread(
                self._store.finish_publication,
                request.request_id,
                status="failed",
                summary=summary,
                error=error,
            )
            return PublicationOutcome("failed", summary, error=error)

        assert route is not None
        receiver_id = int(route["owner_user_id"])
        external_message_id = str(uuid5(NAMESPACE_URL, f"aurora-dashboard-publication:{request.request_id}"))
        message_row, created = await asyncio.to_thread(
            self._store.create_message,
            client_message_id=external_message_id,
            sender_id=self._bot_id(),
            receiver_id=receiver_id,
            message_type="text",
            content=request.text,
            attachment_id=None,
            source_publication_request_id=request.request_id,
        )
        summary = "Dashboard reply accepted"
        await asyncio.to_thread(
            self._store.finish_publication,
            request.request_id,
            status="accepted",
            summary=summary,
            external_message_id=external_message_id,
        )
        if created:
            await self._publish(receiver_id, {"type": "private_message", "message": self._message(message_row)})
        return PublicationOutcome("accepted", summary, external_message_id=external_message_id)

    async def recover_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        row = await asyncio.to_thread(self._store.fetch_one, self._publication_query(), (request.request_id,))
        if row is None:
            return PublicationOutcome(
                "failed",
                "Dashboard reply was interrupted before dispatch",
                error="interrupted_before_dispatch",
            )
        return self._publication_outcome(row, request)

    async def _register_context(self, owner_user_id: int, client_message_id: str) -> dict[str, str]:
        external_event_id = str(uuid5(NAMESPACE_URL, f"aurora-dashboard-event:{client_message_id}"))
        external_message_id = str(uuid5(NAMESPACE_URL, f"aurora-dashboard-message:{client_message_id}"))
        route_ref = str(uuid5(NAMESPACE_URL, f"aurora-dashboard-route:{external_event_id}"))
        conversation_ref = "dashboard.local:owner"
        actor_ref = "owner.local"
        await asyncio.to_thread(
            self._store.register_reply_route,
            route_ref=route_ref,
            external_event_id=external_event_id,
            external_message_id=external_message_id,
            owner_user_id=owner_user_id,
            conversation_ref=conversation_ref,
            actor_ref=actor_ref,
        )
        return {
            "endpoint_id": DASHBOARD_ENDPOINT,
            "external_event_id": external_event_id,
            "external_message_id": external_message_id,
            "conversation_ref": conversation_ref,
            "actor_ref": actor_ref,
            "audience_ref": DASHBOARD_AUDIENCE,
            "reply_route_ref": route_ref,
        }

    async def _validate_publication(
        self, request: PublicationExecutionRequest
    ) -> tuple[sqlite3.Row | None, str | None]:
        error = None
        if request.capability != DASHBOARD_REPLY_CAPABILITY:
            error = f"unsupported Dashboard capability: {request.capability}"
        elif request.endpoint_id != DASHBOARD_ENDPOINT or request.operation != "reply":
            error = "Dashboard only accepts reply Publications for dashboard.local"
        elif not request.text:
            error = "Dashboard Publication text must be non-empty"
        elif request.source_audience_ref != DASHBOARD_AUDIENCE or request.target_audience_ref != DASHBOARD_AUDIENCE:
            error = "Dashboard Publication audience is invalid"
        elif request.route_ref is None:
            error = "Dashboard Publication route is missing"
        if error is not None:
            return None, error
        route = await asyncio.to_thread(
            self._store.fetch_one,
            """
            SELECT r.* FROM dashboard_reply_routes r JOIN users u ON u.id = r.owner_user_id
            WHERE r.route_ref = ? AND u.username = ? AND u.is_bot = 0
            """,
            (request.route_ref, self._configuration.owner_username),
        )
        if route is None:
            return None, "Dashboard reply route is unknown"
        return route, None

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
        reply_client_id = command_reply_id(receiver_id, source_client_message_id)
        row, _created = await asyncio.to_thread(
            self._store.create_message,
            client_message_id=reply_client_id,
            sender_id=self._bot_id(),
            receiver_id=receiver_id,
            message_type="text",
            content=text,
            attachment_id=None,
        )
        return self._message(row)

    async def _direct_reply(self, receiver_id: int, text: str, stable_id: str) -> dict[str, Any]:
        await self.require_owner(receiver_id)
        client_message_id = str(uuid5(NAMESPACE_URL, f"aurora-dashboard-direct:{stable_id}"))
        row, created = await asyncio.to_thread(
            self._store.create_message,
            client_message_id=client_message_id,
            sender_id=self._bot_id(),
            receiver_id=receiver_id,
            message_type="text",
            content=text,
            attachment_id=None,
        )
        message = self._message(row)
        if created:
            await self._publish(receiver_id, {"type": "private_message", "message": message})
        return message

    @staticmethod
    def _publication_query() -> str:
        return "SELECT * FROM dashboard_publications WHERE request_id = ?"

    @staticmethod
    def _publication_outcome(row: sqlite3.Row, request: PublicationExecutionRequest) -> PublicationOutcome:
        if (
            any(
                str(row[name]) != expected
                for name, expected in (
                    ("capability", request.capability),
                    ("endpoint_id", request.endpoint_id),
                    ("operation", request.operation),
                    ("text", request.text),
                )
            )
            or row["route_ref"] != request.route_ref
        ):
            return PublicationOutcome(
                "failed",
                "Dashboard publication idempotency conflict",
                error="request_id_reused_with_different_content",
            )
        status = str(row["status"])
        if status == "dispatch_started":
            return PublicationOutcome(
                "delivery_unknown",
                "Dashboard reply delivery is unknown",
                error="dispatch_started_without_terminal_outcome",
            )
        if status == "accepted":
            return PublicationOutcome(
                "accepted",
                str(row["summary"]),
                external_message_id=str(row["external_message_id"]),
            )
        return PublicationOutcome("failed", str(row["summary"]), error=str(row["error"]))

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
