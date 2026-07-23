"""仪表盘聊天输入的纯函数命令路由工具。

将仪表盘 WebSocket 消息解析为 RuntimeInput，并提供命令识别与消息匹配能力。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.localhost.command_types import InputOrigin, RuntimeInput


@dataclass(frozen=True, slots=True, kw_only=True)
class PrivateMessageInput:
    """从 WebSocket 消息中解析出的私聊输入结构。"""

    client_message_id: str
    """客户端生成的消息唯一标识。"""
    receiver_id: int
    """消息接收者用户 ID。"""
    message_type: str
    """消息类型，如 text、image、file 等。"""
    content: str | None
    """文本内容（非文本类型可为 None）。"""
    attachment_id: int | None
    """附件 ID（无附件时为 None）。"""
    is_bot: bool
    """接收者是否为 Bot。"""


def command_name(content: str) -> str:
    """提取命令名（去掉空白和参数后的第一个词，转小写）。"""
    return content.lstrip().split(maxsplit=1)[0].lower()


def is_conversation_command(content: str) -> bool:
    """判断是否为对话命令（/say 或 /s）。"""
    return command_name(content) in {"/say", "/s"}


def is_quit_command(content: str) -> bool:
    """判断是否为退出命令（/quit、/exit 或 /q）。"""
    return command_name(content) in {"/quit", "/exit", "/q"}


def command_reply_id(receiver_id: int, source_client_message_id: str) -> str:
    """为命令回复生成确定性的 client_message_id。"""
    return str(uuid5(NAMESPACE_URL, f"aurora-dashboard-command:{receiver_id}:{source_client_message_id}"))


def message_matches(message: dict[str, Any], parsed: PrivateMessageInput) -> bool:
    """检查持久化消息与解析输入是否一致（幂等性验证）。"""
    attachment = message.get("attachment")
    stored_attachment_id = attachment.get("attachment_id") if isinstance(attachment, dict) else None
    return (
        message.get("receiver_id") == parsed.receiver_id
        and message.get("message_type") == parsed.message_type
        and message.get("content") == parsed.content
        and stored_attachment_id == parsed.attachment_id
    )


def dashboard_input(parsed: PrivateMessageInput) -> RuntimeInput:
    """将解析后的私聊消息转换为 Dashboard 来源的 RuntimeInput。"""
    data: dict[str, Any] = {"chat_message_id": parsed.client_message_id, "channel": "owner_bot_chat"}
    return RuntimeInput(
        text=parsed.content or "",
        origin=InputOrigin.DASHBOARD,
        session_id="dashboard:owner",
        source_app="dashboard.chat",
        source_instance="local",
        idempotency_key=parsed.client_message_id,
        data=data,
    )
