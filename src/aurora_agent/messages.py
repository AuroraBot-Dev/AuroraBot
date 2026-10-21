"""模型无关的四角色消息与调用配对约束。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from aurora_agent.data import freeze_object

if TYPE_CHECKING:
    from collections.abc import Mapping

type ChatRole = Literal["system", "message", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.call_id.strip() or not self.name.strip():
            raise ValueError("工具调用需要非空身份与名称")
        object.__setattr__(self, "arguments", freeze_object(self.arguments))


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    is_error: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if self.role not in {"system", "message", "assistant", "tool"}:
            raise ValueError("未知消息角色")
        if self.role in {"system", "message"}:
            if not self.content.strip() or self.tool_calls or self.tool_call_id is not None or self.is_error:
                raise ValueError("输入和系统消息需要正文，不能携带工具协议字段")
        elif self.role == "assistant":
            if (not self.content.strip() and not self.tool_calls) or self.tool_call_id is not None or self.is_error:
                raise ValueError("模型消息需要正文或工具调用")
            ids = [call.call_id for call in self.tool_calls]
            if len(ids) != len(set(ids)):
                raise ValueError("同一模型消息中的调用身份不能重复")
        elif not self.tool_call_id or self.tool_calls:
            raise ValueError("工具结果需要对应的调用身份")

    @classmethod
    def system(cls, content: str) -> ChatMessage:
        return cls("system", content)

    @classmethod
    def message(cls, content: str) -> ChatMessage:
        return cls("message", content)

    @classmethod
    def assistant(cls, content: str = "", *, tool_calls: tuple[ToolCall, ...] = ()) -> ChatMessage:
        return cls("assistant", content, tool_calls)

    @classmethod
    def tool(cls, call_id: str, content: str, *, is_error: bool = False) -> ChatMessage:
        return cls("tool", content, tool_call_id=call_id, is_error=is_error)


def validate_history(messages: tuple[ChatMessage, ...], *, allow_pending: bool = False) -> None:
    """运行记录不含 system；未配对调用后只能追加对应工具结果。"""
    seen: set[str] = set()
    pending: set[str] = set()
    for message in messages:
        if not isinstance(message, ChatMessage) or message.role == "system":
            raise ValueError("运行历史只接纳 message、assistant、tool 消息")
        if message.role == "tool":
            if message.tool_call_id not in pending:
                raise ValueError("工具结果必须匹配一个未回答的调用")
            pending.remove(message.tool_call_id)
            continue
        if pending:
            raise ValueError("工具调用全部配对前不能追加输入或再次推理")
        for call in message.tool_calls:
            if call.call_id in seen:
                raise ValueError("运行内工具调用身份不能重复")
            seen.add(call.call_id)
            pending.add(call.call_id)
    if pending and not allow_pending:
        raise ValueError("初始历史与模型请求不能包含未配对工具调用")
