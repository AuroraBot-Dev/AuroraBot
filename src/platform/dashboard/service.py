"""Dashboard 聊天服务、持久化编排与 Bot 因果桥接。"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from src.platform.dashboard.communication import ChatError, DashboardCommunication
from src.platform.dashboard.routing import PrivateMessageInput, is_conversation_command, message_matches
from src.platform.dashboard.store import ChatStore, new_token, token_digest

if TYPE_CHECKING:
    import sqlite3

    from src.contracts.configuration import DashboardConfig
    from src.contracts.ports import InteractiveInputPort
    from src.contracts.tool import ToolExecutionRequest, ToolOutcome

_MESSAGE_TYPES = {"text", "image", "file", "audio", "video"}
_ALLOWED_MIME_PREFIXES = ("image/", "audio/", "video/", "text/")
_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_SUBSCRIBER_QUEUE_SIZE = 128


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    SERVICE_NOT_STARTED = "chat service has not started"
    INVALID_TOKEN = "无效的 token"
    OWNER_UNAVAILABLE = "所有者不可用"
    UNAUTHORIZED = "未授权"
    FILE_TOO_LARGE = "文件过大"
    UNSUPPORTED_FILE_TYPE = "不支持的文件类型"
    ATTACHMENT_NOT_FOUND = "附件未找到"
    ATTACHMENT_FORBIDDEN = "禁止访问"
    ATTACHMENT_FILE_MISSING = "附件文件缺失"
    IDEMPOTENCY_CONFLICT = "client_message_id 已被使用"
    INVALID_MESSAGE_ID = "消息标识无效"
    INVALID_PAYLOAD = "消息负载无效"
    BOT_ATTACHMENT_UNSUPPORTED = "Bot 不支持附件消息"
    INVALID_ATTACHMENT_ID = "attachment_id 无效"
    ATTACHMENT_UNAVAILABLE = "附件不可用"
    RECEIVER_NOT_FOUND = "接收者不存在"
    CODE_UNAUTHORIZED = "UNAUTHORIZED"
    CODE_MESSAGE_TOO_LARGE = "MESSAGE_TOO_LARGE"
    CODE_INVALID_PAYLOAD = "INVALID_PAYLOAD"
    CODE_ATTACHMENT_NOT_FOUND = "ATTACHMENT_NOT_FOUND"
    CODE_BOT_ATTACHMENT_UNSUPPORTED = "BOT_ATTACHMENT_UNSUPPORTED"
    CODE_ATTACHMENT_FORBIDDEN = "ATTACHMENT_FORBIDDEN"
    CODE_IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    CODE_RECEIVER_NOT_FOUND = "RECEIVER_NOT_FOUND"


class ChatService:
    """Dashboard 聊天服务：认证、消息路由、发布/订阅和附件管理的统一入口。"""

    def __init__(
        self,
        configuration: DashboardConfig,
        input_port: InteractiveInputPort,
    ) -> None:
        """初始化聊天服务，组装存储、通信层和订阅表。

        Args:
            configuration: Dashboard 配置。
            input_port: 交互式输入端口，用于将用户命令路由到 localhost。
        """
        self.configuration = configuration
        self.store = ChatStore(configuration.database_path)
        self._subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._owner_id: int | None = None
        self._bot_id: int | None = None
        self._communication = DashboardCommunication(
            configuration,
            self.store,
            input_port,
            lambda: self.bot_id,
            self.publish,
        )

    async def start(self) -> None:
        """启动聊天服务：初始化数据库、确保所有者和 Bot 用户存在。"""
        await asyncio.to_thread(self.store.initialize)
        owner = await asyncio.to_thread(
            self.store.ensure_owner,
            self.configuration.owner_username,
        )
        bot = await asyncio.to_thread(
            self.store.ensure_bot,
            self.configuration.bot.username,
            self.configuration.bot.display_name,
            self.configuration.bot.avatar_url,
        )
        self._owner_id = int(owner["id"])
        self._bot_id = int(bot["id"])

    @property
    def owner_id(self) -> int:
        """配置中 Dashboard 所有者的用户 ID。"""
        if self._owner_id is None:
            raise RuntimeError(_Msg.SERVICE_NOT_STARTED)
        return self._owner_id

    @property
    def bot_id(self) -> int:
        """Dashboard Bot 的用户 ID。"""
        if self._bot_id is None:
            raise RuntimeError(_Msg.SERVICE_NOT_STARTED)
        return self._bot_id

    async def login(self, bootstrap_token: str) -> dict[str, Any]:
        """使用引导 token 验证并创建会话，返回访问令牌。

        使用恒定时间比较防止时序攻击。
        """
        expected = await asyncio.to_thread(self.store.bootstrap_token)
        if not secrets.compare_digest(bootstrap_token.strip(), expected):
            raise ChatError(_Msg.CODE_UNAUTHORIZED, _Msg.INVALID_TOKEN, 401)
        row = await asyncio.to_thread(
            self.store.fetch_one,
            "SELECT * FROM users WHERE id = ? AND is_owner = 1 AND is_bot = 0",
            (self.owner_id,),
        )
        if row is None:
            raise ChatError(_Msg.CODE_UNAUTHORIZED, _Msg.OWNER_UNAVAILABLE, 401)
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
        """销毁指定 token 对应的会话。"""
        await asyncio.to_thread(self.store.execute, "DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))

    async def authenticate(self, token: str) -> dict[str, Any]:
        """验证 token 并返回对应用户信息。

        同时校验过期时间和所有者身份。
        """
        row = await asyncio.to_thread(
            self.store.fetch_one,
            """
            SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ? AND u.id = ? AND u.is_owner = 1 AND u.is_bot = 0
            """,
            (token_digest(token), datetime.now(UTC).isoformat(), self.owner_id),
        )
        if row is None:
            raise ChatError(_Msg.CODE_UNAUTHORIZED, _Msg.UNAUTHORIZED, 401)
        return dict(row)

    async def list_users(self, current_user_id: int) -> list[dict[str, Any]]:
        """列出除当前用户外的所有 Bot 用户。"""
        rows = await asyncio.to_thread(
            self.store.fetch_all,
            "SELECT * FROM users WHERE id != ? AND is_bot = 1 ORDER BY username",
            (current_user_id,),
        )
        return [self._user(row) for row in rows]

    async def private_history(
        self, current_user_id: int, peer_user_id: int, before_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        """获取与指定用户的私聊历史消息（分页倒序查询，返回时间正序）。

        limit 被截断为 [1, 100] 范围。
        """
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
        """增量同步指定 ID 之后的消息，最多返回 200 条。"""
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
        """上传附件文件：校验大小和类型，原子写入磁盘，记录到数据库。

        若写入后数据库插入失败，自动清理已写入的文件。
        """
        if len(data) > self.configuration.max_upload_bytes:
            raise ChatError(_Msg.CODE_MESSAGE_TOO_LARGE, _Msg.FILE_TOO_LARGE, 413)
        if not (mime_type.startswith(_ALLOWED_MIME_PREFIXES) or mime_type in _ALLOWED_MIME_TYPES):
            raise ChatError(_Msg.CODE_INVALID_PAYLOAD, _Msg.UNSUPPORTED_FILE_TYPE)
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
            # 若数据库写入失败则回滚文件
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
        """下载附件：验证访问权限、检查文件存在性，返回文件路径和元信息。

        权限规则：附件所有者或参与过相关消息的发送/接收者可以下载。
        """
        row = await asyncio.to_thread(
            self.store.fetch_one,
            "SELECT * FROM attachments WHERE id = ?",
            (attachment_id,),
        )
        if row is None:
            raise ChatError(_Msg.CODE_ATTACHMENT_NOT_FOUND, _Msg.ATTACHMENT_NOT_FOUND, 404)
        allowed = int(row["owner_id"]) == user_id
        if not allowed:
            message = await asyncio.to_thread(
                self.store.fetch_one,
                "SELECT id FROM messages WHERE attachment_id = ? AND (sender_id = ? OR receiver_id = ?)",
                (attachment_id, user_id, user_id),
            )
            allowed = message is not None
        if not allowed:
            raise ChatError(_Msg.CODE_ATTACHMENT_FORBIDDEN, _Msg.ATTACHMENT_FORBIDDEN, 403)
        # 验证文件路径在 upload 目录内（防目录遍历）
        path = await asyncio.to_thread((self.configuration.upload_dir / str(row["stored_name"])).resolve)
        upload_root = await asyncio.to_thread(self.configuration.upload_dir.resolve)
        exists = await asyncio.to_thread(path.is_file)
        if not path.is_relative_to(upload_root) or not exists:
            raise ChatError(_Msg.CODE_ATTACHMENT_NOT_FOUND, _Msg.ATTACHMENT_FILE_MISSING, 404)
        return path, str(row["mime_type"]), str(row["original_name"])

    async def send_private_message(self, sender_id: int, event: dict[str, Any]) -> dict[str, Any]:
        """发送私聊消息：解析、验证、幂等处理、路由至 Bot 或直接发布。

        若消息的目标是 Bot，则触发 Bot 命令处理流程；否则直接发布给目标用户。
        """
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
            raise ChatError(_Msg.CODE_IDEMPOTENCY_CONFLICT, _Msg.IDEMPOTENCY_CONFLICT, 409)
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
        """验证 WebSocket 传入的私聊消息事件并解析为结构化输入。

        校验 client_message_id（UUID 格式）、receiver_id、message_type、content 和 attachment。
        若目标为 Bot，额外校验发送者是 Dashboard 所有者且消息为文本。
        """
        client_message_id = str(event.get("client_message_id", ""))
        try:
            UUID(client_message_id)
            receiver_id = int(event.get("receiver_id", 0))
        except (TypeError, ValueError) as error:
            raise ChatError(_Msg.CODE_INVALID_PAYLOAD, _Msg.INVALID_MESSAGE_ID) from error
        receiver = await self._require_user(receiver_id)
        message_type = str(event.get("message_type") or "text")
        content_value = event.get("content")
        content = str(content_value).strip() if content_value is not None else None
        if (
            message_type not in _MESSAGE_TYPES
            or (message_type == "text" and not content)
            or (message_type != "text" and event.get("attachment_id") is None)
        ):
            raise ChatError(_Msg.CODE_INVALID_PAYLOAD, _Msg.INVALID_PAYLOAD)
        if bool(receiver["is_bot"]):
            await self._communication.require_owner(sender_id)
            if message_type != "text":
                raise ChatError(_Msg.CODE_BOT_ATTACHMENT_UNSUPPORTED, _Msg.BOT_ATTACHMENT_UNSUPPORTED)
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
        """验证附件 ID：检查其属于当前用户且存在。"""
        if value is None:
            return None
        if not isinstance(value, (int, str)) or isinstance(value, bool):
            raise ChatError(_Msg.CODE_INVALID_PAYLOAD, _Msg.INVALID_ATTACHMENT_ID)
        try:
            attachment_id = int(value)
        except (TypeError, ValueError) as error:
            raise ChatError(_Msg.CODE_INVALID_PAYLOAD, _Msg.INVALID_ATTACHMENT_ID) from error
        attachment = await asyncio.to_thread(
            self.store.fetch_one,
            "SELECT id FROM attachments WHERE id = ? AND owner_id = ?",
            (attachment_id, sender_id),
        )
        if attachment is None:
            raise ChatError(_Msg.CODE_ATTACHMENT_FORBIDDEN, _Msg.ATTACHMENT_UNAVAILABLE, 403)
        return attachment_id

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """执行 Dashboard Tool，委托给通信层处理。"""
        return await self._communication.execute_tool(request)

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """恢复 Dashboard Tool 状态，委托给通信层处理。"""
        return await self._communication.recover_tool(request)

    async def subscribe(self, user_id: int) -> asyncio.Queue[dict[str, Any]]:
        """为用户创建事件订阅队列。

        若用户首次订阅则广播上线通知。
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(_SUBSCRIBER_QUEUE_SIZE)
        first = not self._subscribers.get(user_id)
        self._subscribers.setdefault(user_id, set()).add(queue)
        if first:
            await self.broadcast({"type": "presence", "user_id": user_id, "online": True}, exclude=user_id)
        return queue

    async def unsubscribe(self, user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """移除用户的订阅队列，若所有队列移除后广播下线通知。"""
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
        """向指定用户的所有订阅队列发布事件，支持排除特定队列。"""
        for queue in tuple(self._subscribers.get(user_id, ())):
            if queue is not exclude_queue:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(event)

    async def broadcast(self, event: dict[str, Any], *, exclude: int | None = None) -> None:
        """向所有在线用户广播事件，支持排除指定用户。"""
        for user_id in tuple(self._subscribers):
            if user_id != exclude:
                await self.publish(user_id, event)

    async def _require_user(self, user_id: int) -> dict[str, Any]:
        """验证用户 ID 存在且为 Bot 用户。"""
        row = await asyncio.to_thread(
            self.store.fetch_one,
            "SELECT * FROM users WHERE id = ? AND is_bot = 1",
            (user_id,),
        )
        if row is None:
            raise ChatError(_Msg.CODE_RECEIVER_NOT_FOUND, _Msg.RECEIVER_NOT_FOUND, 404)
        return dict(row)

    def _user(self, row: sqlite3.Row) -> dict[str, Any]:
        """将数据库用户行转换为 API 用户字典。"""
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
        """将数据库消息行（含 JOIN 的附件字段）转换为 API 消息字典。"""
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
        """原子写入文件：先写临时文件后再原子重命名，失败自动清理。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.urandom(6).hex()}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
