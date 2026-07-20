"""Dashboard chat service, persistence orchestration, and Bot causal bridge."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from src.platform.dashboard.communication import ChatError, DashboardCommunication
from src.platform.dashboard.routing import PrivateMessageInput, is_conversation_command, message_matches
from src.platform.dashboard.security import hash_password, new_token, token_digest, verify_password
from src.platform.dashboard.store import ChatStore

if TYPE_CHECKING:
    from src.contracts.configuration import DashboardConfig
    from src.localhost.ports import InteractiveInputPort, PublicationExecutionRequest, PublicationOutcome

_MESSAGE_TYPES = {"text", "image", "file", "audio", "video"}
_ALLOWED_MIME_PREFIXES = ("image/", "audio/", "video/", "text/")
_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}


class ChatService:
    def __init__(self, configuration: DashboardConfig, input_port: InteractiveInputPort) -> None:
        self.configuration = configuration
        self.store = ChatStore(configuration.database_path)
        self._subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._bot_id: int | None = None
        self._communication = DashboardCommunication(
            configuration,
            self.store,
            input_port,
            lambda: self.bot_id,
            self.publish,
        )

    async def start(self) -> None:
        await asyncio.to_thread(self.store.initialize)
        bot = await asyncio.to_thread(
            self.store.ensure_bot,
            self.configuration.bot.username,
            self.configuration.bot.display_name,
            self.configuration.bot.avatar_url,
        )
        self._bot_id = int(bot["id"])

    @property
    def bot_id(self) -> int:
        if self._bot_id is None:
            raise RuntimeError("chat service has not started")
        return self._bot_id

    async def register(self, username: str, password: str) -> dict[str, Any]:
        normalized = username.strip()
        if not normalized or len(normalized) > 64 or not password:
            raise ChatError("INVALID_PAYLOAD", "Username and password are required")
        try:
            row = await asyncio.to_thread(self.store.create_user, normalized, hash_password(password))
        except sqlite3.IntegrityError as error:
            raise ChatError("USERNAME_EXISTS", "Username already exists", 409) from error
        return self._user(row)

    async def login(self, username: str, password: str) -> dict[str, Any]:
        row = await asyncio.to_thread(
            self.store.fetch_one,
            "SELECT * FROM users WHERE username = ?",
            (username.strip(),),
        )
        if row is None or bool(row["is_bot"]) or not verify_password(password, str(row["password_hash"])):
            raise ChatError("UNAUTHORIZED", "Invalid credentials", 401)
        token = new_token()
        now = datetime.now(UTC)
        await asyncio.to_thread(
            self.store.execute,
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (
                token_digest(token),
                int(row["id"]),
                (now + timedelta(seconds=self.configuration.session_ttl_seconds)).isoformat(),
                now.isoformat(),
            ),
        )
        return {"access_token": token, "token_type": "bearer", "user": self._user(row)}

    async def logout(self, token: str) -> None:
        await asyncio.to_thread(self.store.execute, "DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))

    async def authenticate(self, token: str) -> dict[str, Any]:
        row = await asyncio.to_thread(
            self.store.fetch_one,
            """
            SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_bot = 0
            """,
            (token_digest(token), datetime.now(UTC).isoformat()),
        )
        if row is None:
            raise ChatError("UNAUTHORIZED", "Unauthorized", 401)
        return dict(row)

    async def list_users(self, current_user_id: int) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self.store.fetch_all,
            "SELECT * FROM users WHERE id != ? ORDER BY is_bot DESC, username",
            (current_user_id,),
        )
        return [self._user(row) for row in rows]

    async def private_history(
        self, current_user_id: int, peer_user_id: int, before_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        await self._require_user(peer_user_id)
        bounded = min(max(limit, 1), 100)
        parameters: list[object] = [current_user_id, peer_user_id, peer_user_id, current_user_id]
        before_clause = ""
        if before_id is not None:
            before_clause = "AND m.id < ?"
            parameters.append(before_id)
        parameters.append(bounded)
        rows = await asyncio.to_thread(
            self.store.messages_with_attachments,
            f"""
            SELECT m.*, a.original_name, a.stored_name, a.mime_type, a.size
            FROM messages m LEFT JOIN attachments a ON a.id = m.attachment_id
            WHERE ((m.sender_id = ? AND m.receiver_id = ?) OR (m.sender_id = ? AND m.receiver_id = ?))
            {before_clause}
            ORDER BY m.id DESC LIMIT ?
            """,
            parameters,
        )
        return [self._message(row) for row in reversed(rows)]

    async def sync_messages(self, current_user_id: int, after_id: int) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self.store.messages_with_attachments,
            """
            SELECT m.*, a.original_name, a.stored_name, a.mime_type, a.size
            FROM messages m LEFT JOIN attachments a ON a.id = m.attachment_id
            WHERE m.id > ? AND (m.sender_id = ? OR m.receiver_id = ?)
            ORDER BY m.id ASC LIMIT 200
            """,
            (max(0, after_id), current_user_id, current_user_id),
        )
        return [self._message(row) for row in rows]

    async def upload_attachment(self, owner_id: int, filename: str, mime_type: str, data: bytes) -> dict[str, Any]:
        if len(data) > self.configuration.max_upload_bytes:
            raise ChatError("MESSAGE_TOO_LARGE", "File is too large", 413)
        if not (mime_type.startswith(_ALLOWED_MIME_PREFIXES) or mime_type in _ALLOWED_MIME_TYPES):
            raise ChatError("INVALID_PAYLOAD", "Unsupported file type")
        original_name = Path(filename or "file").name[:255]
        suffix = Path(original_name).suffix[:16]
        stored_name = f"{uuid4().hex}{suffix}"
        target = self.configuration.upload_dir / stored_name
        await asyncio.to_thread(self._atomic_write, target, data)
        try:
            attachment_id = await asyncio.to_thread(
                self.store.execute,
                """
                INSERT INTO attachments(owner_id, original_name, stored_name, mime_type, size, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (owner_id, original_name, stored_name, mime_type, len(data), datetime.now(UTC).isoformat()),
            )
        except Exception:
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
        return {
            "attachment_id": attachment_id,
            "file_name": original_name,
            "mime_type": mime_type,
            "size": len(data),
            "url": f"/api/attachments/{attachment_id}/download",
        }

    async def attachment_download(self, attachment_id: int, user_id: int) -> tuple[Path, str, str]:
        row = await asyncio.to_thread(
            self.store.fetch_one,
            "SELECT * FROM attachments WHERE id = ?",
            (attachment_id,),
        )
        if row is None:
            raise ChatError("ATTACHMENT_NOT_FOUND", "Attachment not found", 404)
        allowed = int(row["owner_id"]) == user_id
        if not allowed:
            message = await asyncio.to_thread(
                self.store.fetch_one,
                "SELECT id FROM messages WHERE attachment_id = ? AND (sender_id = ? OR receiver_id = ?)",
                (attachment_id, user_id, user_id),
            )
            allowed = message is not None
        if not allowed:
            raise ChatError("ATTACHMENT_FORBIDDEN", "Forbidden", 403)
        path = await asyncio.to_thread((self.configuration.upload_dir / str(row["stored_name"])).resolve)
        upload_root = await asyncio.to_thread(self.configuration.upload_dir.resolve)
        exists = await asyncio.to_thread(path.is_file)
        if not path.is_relative_to(upload_root) or not exists:
            raise ChatError("ATTACHMENT_NOT_FOUND", "Attachment file missing", 404)
        return path, str(row["mime_type"]), str(row["original_name"])

    async def send_private_message(self, sender_id: int, event: dict[str, Any]) -> dict[str, Any]:
        parsed = await self._validate_private_message(sender_id, event)
        routed_input = parsed.is_bot and parsed.message_type == "text"
        is_command = routed_input and parsed.content is not None and parsed.content.lstrip().startswith("/")
        row, created = await asyncio.to_thread(
            self.store.create_message,
            client_message_id=parsed.client_message_id,
            sender_id=sender_id,
            receiver_id=parsed.receiver_id,
            message_type=parsed.message_type,
            content=parsed.content,
            attachment_id=parsed.attachment_id,
            status="processing" if routed_input else "saved",
            amp_message_id=None,
        )
        message_row = await asyncio.to_thread(self.store.message_with_attachment, int(row["id"]))
        assert message_row is not None
        message = self._message(message_row)
        if not created and not message_matches(message, parsed):
            raise ChatError("IDEMPOTENCY_CONFLICT", "client_message_id was already used", 409)
        if not created and message["status"] == "saved":
            if is_command and not is_conversation_command(parsed.content or ""):
                await self._communication.attach_existing_command_reply(
                    message,
                    sender_id,
                    parsed.client_message_id,
                    parsed.content or "",
                )
            return message
        if parsed.is_bot:
            await self._communication.handle_bot_input(sender_id, int(row["id"]), parsed, message, created=created)
        else:
            await self.publish(parsed.receiver_id, {"type": "private_message", "message": message})
        return message

    async def _validate_private_message(self, sender_id: int, event: dict[str, Any]) -> PrivateMessageInput:
        client_message_id = str(event.get("client_message_id", ""))
        try:
            UUID(client_message_id)
            receiver_id = int(event.get("receiver_id", 0))
        except (TypeError, ValueError) as error:
            raise ChatError("INVALID_PAYLOAD", "Message identity is invalid") from error
        receiver = await self._require_user(receiver_id)
        message_type = str(event.get("message_type") or "text")
        content_value = event.get("content")
        content = str(content_value).strip() if content_value is not None else None
        if (
            message_type not in _MESSAGE_TYPES
            or (message_type == "text" and not content)
            or (message_type != "text" and event.get("attachment_id") is None)
        ):
            raise ChatError("INVALID_PAYLOAD", "Message payload is invalid")
        if bool(receiver["is_bot"]):
            await self._communication.require_owner(sender_id)
        attachment_id = await self._validate_attachment(sender_id, event.get("attachment_id"))
        return PrivateMessageInput(
            client_message_id=client_message_id,
            receiver_id=receiver_id,
            message_type=message_type,
            content=content,
            attachment_id=attachment_id,
            is_bot=bool(receiver["is_bot"]),
        )

    async def _validate_attachment(self, sender_id: int, value: object) -> int | None:
        if value is None:
            return None
        if not isinstance(value, (int, str)) or isinstance(value, bool):
            raise ChatError("INVALID_PAYLOAD", "attachment_id is invalid")
        try:
            attachment_id = int(value)
        except (TypeError, ValueError) as error:
            raise ChatError("INVALID_PAYLOAD", "attachment_id is invalid") from error
        attachment = await asyncio.to_thread(
            self.store.fetch_one,
            "SELECT id FROM attachments WHERE id = ? AND owner_id = ?",
            (attachment_id, sender_id),
        )
        if attachment is None:
            raise ChatError("ATTACHMENT_FORBIDDEN", "Attachment is unavailable", 403)
        return attachment_id

    async def execute_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        return await self._communication.execute_publication(request)

    async def recover_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        return await self._communication.recover_publication(request)

    async def subscribe(self, user_id: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        first = not self._subscribers.get(user_id)
        self._subscribers.setdefault(user_id, set()).add(queue)
        if first:
            await self.broadcast({"type": "presence", "user_id": user_id, "online": True}, exclude=user_id)
        return queue

    async def unsubscribe(self, user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._subscribers.get(user_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._subscribers.pop(user_id, None)
            await self.broadcast({"type": "presence", "user_id": user_id, "online": False}, exclude=user_id)

    async def publish(
        self,
        user_id: int,
        event: dict[str, Any],
        *,
        exclude_queue: asyncio.Queue[dict[str, Any]] | None = None,
    ) -> None:
        for queue in tuple(self._subscribers.get(user_id, ())):
            if queue is not exclude_queue:
                queue.put_nowait(event)

    async def broadcast(self, event: dict[str, Any], *, exclude: int | None = None) -> None:
        for user_id in tuple(self._subscribers):
            if user_id != exclude:
                await self.publish(user_id, event)

    async def _require_user(self, user_id: int) -> dict[str, Any]:
        row = await asyncio.to_thread(self.store.fetch_one, "SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None:
            raise ChatError("RECEIVER_NOT_FOUND", "Receiver does not exist", 404)
        return dict(row)

    def _user(self, row: sqlite3.Row) -> dict[str, Any]:
        user_id = int(row["id"])
        return {
            "user_id": user_id,
            "username": str(row["username"]),
            "display_name": str(row["display_name"]),
            "avatar_url": row["avatar_url"],
            "online": bool(row["is_bot"]) or bool(self._subscribers.get(user_id)),
            "is_bot": bool(row["is_bot"]),
        }

    @staticmethod
    def _message(row: sqlite3.Row) -> dict[str, Any]:
        attachment = None
        if row["attachment_id"] is not None:
            attachment = {
                "attachment_id": int(row["attachment_id"]),
                "file_name": str(row["original_name"]),
                "mime_type": str(row["mime_type"]),
                "size": int(row["size"]),
                "url": f"/api/attachments/{int(row['attachment_id'])}/download",
            }
        return {
            "message_id": int(row["id"]),
            "client_message_id": str(row["client_message_id"]),
            "sender_id": int(row["sender_id"]),
            "receiver_id": int(row["receiver_id"]),
            "message_type": str(row["message_type"]),
            "content": row["content"],
            "attachment": attachment,
            "created_at": str(row["created_at"]),
            "status": str(row["status"]),
        }

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.urandom(6).hex()}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
