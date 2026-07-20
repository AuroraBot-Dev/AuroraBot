"""Pure command-routing helpers for Dashboard chat input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.localhost.command_types import InputOrigin, RuntimeInput


@dataclass(frozen=True, slots=True, kw_only=True)
class PrivateMessageInput:
    client_message_id: str
    receiver_id: int
    message_type: str
    content: str | None
    attachment_id: int | None
    is_bot: bool


def command_name(content: str) -> str:
    return content.lstrip().split(maxsplit=1)[0].lower()


def is_conversation_command(content: str) -> bool:
    return command_name(content) in {"/say", "/s"}


def is_quit_command(content: str) -> bool:
    return command_name(content) in {"/quit", "/exit", "/q"}


def command_reply_id(receiver_id: int, source_client_message_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"aurora-dashboard-command:{receiver_id}:{source_client_message_id}"))


def message_matches(message: dict[str, Any], parsed: PrivateMessageInput) -> bool:
    attachment = message.get("attachment")
    stored_attachment_id = attachment.get("attachment_id") if isinstance(attachment, dict) else None
    return (
        message.get("receiver_id") == parsed.receiver_id
        and message.get("message_type") == parsed.message_type
        and message.get("content") == parsed.content
        and stored_attachment_id == parsed.attachment_id
    )


def dashboard_input(parsed: PrivateMessageInput, communication: dict[str, str]) -> RuntimeInput:
    return RuntimeInput(
        text=parsed.content or "",
        origin=InputOrigin.DASHBOARD,
        session_id="dashboard:owner",
        source_app="dashboard.chat",
        source_instance="local",
        reply_capability="org.aurora.dashboard.send_message",
        idempotency_key=parsed.client_message_id,
        data={"chat_message_id": parsed.client_message_id, "communication": communication},
    )
