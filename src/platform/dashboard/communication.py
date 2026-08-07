"""Dashboard 用户消息入口与固定目标 Tool 投递。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.contracts import (
    CommandControl,
    ToolExecutionRequest,
    ToolOutcome,
    ToolOutcomeStatus,
)
from src.platform.dashboard.adapter import DASHBOARD_SEND_CAPABILITY
from src.platform.dashboard.routing import (
    PrivateMessageInput,
    command_reply_id,
    dashboard_input,
    is_conversation_command,
    is_quit_command,
    message_to_api,
)
from src.utils import utc_now

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Awaitable, Callable

    from src.contracts.configuration import DashboardConfig
    from src.contracts.ports import InteractiveInputPort
    from src.platform.dashboard.store import ChatStore

    Publish = Callable[[int, dict[str, Any]], Awaitable[None]]


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    CODE_BOT_OWNER_ONLY = "BOT_OWNER_ONLY"
    BOT_OWNER_ONLY_MSG = "仅允许已配置的 Dashboard 所有者向 Bot 发送消息"
    CODE_BOT_ATTACHMENT_UNSUPPORTED = "BOT_ATTACHMENT_UNSUPPORTED"
    BOT_ATTACHMENT_UNSUPPORTED_MSG = "Bot 不支持附件消息"
    CODE_BOT_UNAVAILABLE = "BOT_UNAVAILABLE"
    BOT_UNAVAILABLE_MSG = "Bot 不可用"


class ChatError(RuntimeError):
    """Dashboard 聊天域的统一错误类型，携带错误码和 HTTP 状态码。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class DashboardCommunication:
    """在 Platform 边界内管理 Dashboard 用户 ID 和持久化投递状态。"""

    def __init__(
        self,
        configuration: DashboardConfig,
        store: ChatStore,
        input_port: InteractiveInputPort,
        bot_id: Callable[[], int],
        publish: Publish,
    ) -> None:
        """绑定配置、存储、输入端口和消息发布能力。

        Args:
            configuration: Dashboard 配置。
            store: 聊天持久化存储。
            input_port: 交互式输入端口，用于路由用户命令到 localhost。
            bot_id: 获取 Bot 用户 ID 的回调。
            publish: 向指定用户推送消息的异步回调。
        """
        self._configuration = configuration
        self._store = store
        self._input_port = input_port
        self._bot_id = bot_id
        self._publish = publish

    async def require_owner(self, user_id: int) -> None:
        """验证用户是否为配置中指定的 Dashboard 所有者。

        Raises:
            ChatError: 若非所有者。
        """
        owner = await asyncio.to_thread(
            self._store.fetch_one,
            "SELECT id FROM users WHERE id = ? AND username = ? AND is_owner = 1 AND is_bot = 0",
            (user_id, self._configuration.owner_username),
        )
        if owner is None:
            raise ChatError(_Msg.CODE_BOT_OWNER_ONLY, _Msg.BOT_OWNER_ONLY_MSG, 403)

    async def handle_bot_input(
        self,
        sender_id: int,
        row_id: int,
        parsed: PrivateMessageInput,
        message: dict[str, Any],
        *,
        created: bool,
    ) -> None:
        """处理发送给 Bot 的消息：路由至 localhost 并持久化命令回复。

        仅处理文本消息；重复的旧命令不被重新路由。

        Args:
            sender_id: 发送者用户 ID。
            row_id: 消息数据库行 ID。
            parsed: 解析后的私聊输入。
            message: 消息字典（会被原地修改以附加 _post_ack）。
            created: 消息是否为新建（否则为幂等重放）。

        Raises:
            ChatError: Bot 不可用或消息类型不支持时。
        """
        if parsed.message_type != "text":
            raise ChatError(_Msg.CODE_BOT_ATTACHMENT_UNSUPPORTED, _Msg.BOT_ATTACHMENT_UNSUPPORTED_MSG)
        content = parsed.content or ""
        is_command = content.lstrip().startswith("/")
        # 非新建的旧命令（且非对话命令）不重新路由
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
            raise ChatError(_Msg.CODE_BOT_UNAVAILABLE, _Msg.BOT_UNAVAILABLE_MSG, 503) from error

    async def attach_existing_command_reply(
        self,
        message: dict[str, Any],
        receiver_id: int,
        source_client_message_id: str,
        content: str,
    ) -> None:
        """为已存在的重复命令消息附加之前已持久化的回复。

        当客户端重发相同 client_message_id 时，将之前 Bot 已生成的回复
        附带到消息上返回，避免重新执行命令。
        """
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
        message["_post_ack"] = {"reply": message_to_api(message_row), "control": control}

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """执行 Dashboard Tool 请求：将文本消息发送给配置的所有者。

        含幂等性检查、验证、持久化和发布流程。
        """
        error = self._validate_tool(request)
        text = request.parameters.get("text")
        now = await asyncio.to_thread(utc_now)
        record, created_request = await asyncio.to_thread(
            self._store.begin_tool_request,
            request.request_id,
            _request_digest(request),
            text if isinstance(text, str) else "",
            now,
        )
        if not created_request:
            return self._tool_outcome(record, request)
        if error is not None:
            return await self._finish_failure(request.request_id, error)

        owner = await asyncio.to_thread(
            self._store.fetch_one,
            "SELECT id FROM users WHERE username = ? AND is_owner = 1 AND is_bot = 0",
            (self._configuration.owner_username,),
        )
        if owner is None:
            return await self._finish_failure(request.request_id, "已配置的 Dashboard 所有者不可用")
        owner_id = int(owner["id"])
        message_id = str(uuid5(NAMESPACE_URL, f"aurora-dashboard-tool:{request.request_id}"))
        summary = "Dashboard 消息已发送"
        message_row, created = await asyncio.to_thread(
            self._store.complete_tool_message,
            request_id=request.request_id,
            message_id=message_id,
            sender_id=self._bot_id(),
            receiver_id=owner_id,
            text=str(text),
            summary=summary,
            now=await asyncio.to_thread(utc_now),
        )
        if created:
            await self._publish(owner_id, {"type": "private_message", "message": message_to_api(message_row)})
        return ToolOutcome(ToolOutcomeStatus.SUCCEEDED, summary, result={"message_id": message_id})

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """恢复 Dashboard Tool 执行状态。

        用于故障恢复：查询持久化记录，若有已知结果则返回，否则返回中断错误。
        """
        row = await asyncio.to_thread(
            self._store.recover_tool_request, request.request_id, await asyncio.to_thread(utc_now)
        )
        if row is None:
            return ToolOutcome(
                ToolOutcomeStatus.FAILED, "Dashboard 发送在分发前被中断", error="interrupted_before_dispatch"
            )
        return self._tool_outcome(row, request)

    @staticmethod
    def _validate_tool(request: ToolExecutionRequest) -> str | None:
        """验证 Tool 请求的 capability 和参数是否合法。"""
        if request.capability != DASHBOARD_SEND_CAPABILITY:
            return f"不支持的 Dashboard capability: {request.capability}"
        if set(request.parameters) != {"text"}:
            return "Dashboard 发送参数只能包含 text"
        text = request.parameters.get("text")
        if not isinstance(text, str) or not text.strip():
            return "Dashboard 发送的 text 必须是非空字符串"
        return None

    async def _finish_failure(self, request_id: str, error: str) -> ToolOutcome:
        """将 Tool 请求标记为失败并返回结果。"""
        summary = "Dashboard 发送失败"
        await asyncio.to_thread(
            self._store.execute,
            "UPDATE dashboard_tool_requests SET status = 'failed', summary = ?, error = ?, updated_at = ? "
            "WHERE request_id = ?",
            (summary, error, await asyncio.to_thread(utc_now), request_id),
        )
        return ToolOutcome(ToolOutcomeStatus.FAILED, summary, error=error)

    @staticmethod
    def _tool_outcome(row: sqlite3.Row, request: ToolExecutionRequest) -> ToolOutcome:
        """从持久化记录构造 ToolOutcome，同时校验请求摘要的幂等性。"""
        digest = row["request_digest"]
        if digest is None:
            return ToolOutcome(
                ToolOutcomeStatus.UNKNOWN, "Dashboard 发送标识未知", error="legacy_request_identity_unknown"
            )
        if str(digest) != _request_digest(request):
            return ToolOutcome(
                ToolOutcomeStatus.FAILED, "Dashboard Tool 幂等性冲突", error="request_id_reused_with_different_content"
            )
        status = str(row["status"])
        if status == "dispatch_started":
            return ToolOutcome(
                ToolOutcomeStatus.UNKNOWN,
                "Dashboard 消息投递结果未知",
                error="dispatch_started_without_terminal_outcome",
            )
        if status == "succeeded":
            return ToolOutcome(
                ToolOutcomeStatus.SUCCEEDED, str(row["summary"]), result={"message_id": str(row["external_message_id"])}
            )
        return ToolOutcome(ToolOutcomeStatus.FAILED, str(row["summary"]), error=str(row["error"]))

    async def _persist_command_reply(
        self,
        receiver_id: int,
        source_client_message_id: str,
        text: str | None,
        *,
        publish_reply: bool,
    ) -> dict[str, Any] | None:
        """持久化 Bot 对用户命令的回复消息。

        Args:
            receiver_id: 命令发送者（回复目标）。
            source_client_message_id: 原始命令的 client_message_id。
            text: 回复文本内容。
            publish_reply: 是否需要发布回复到 WebSocket。

        Returns:
            构造的消息字典，若 publish_reply 为 False 则返回 None。
        """
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
        return message_to_api(row)


def _request_digest(request: ToolExecutionRequest) -> str:
    """计算 ToolExecutionRequest 的规范 SHA-256 摘要，用于幂等性校验。"""
    canonical = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
