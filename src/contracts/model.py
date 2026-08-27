"""四角色聊天、模型与工具的最小公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.tool import ToolDefinition

ChatRole = Literal["system", "message", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """assistant 请求的一次工具调用。"""

    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.call_id or not self.name:
            raise ValueError("ToolCall requires call_id and name")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """AgentTree 内部使用的四角色消息。"""

    role: ChatRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    is_error: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        if self.role in {"system", "message"}:
            if not self.content.strip() or self.tool_calls or self.tool_call_id is not None or self.is_error:
                raise ValueError(f"invalid {self.role} message")
            return
        if self.role == "assistant":
            if (not self.content.strip() and not self.tool_calls) or self.tool_call_id is not None or self.is_error:
                raise ValueError("invalid assistant message")
            identifiers = [call.call_id for call in self.tool_calls]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("assistant Tool call IDs must be unique")
            return
        if not self.content.strip() or not self.tool_call_id or self.tool_calls:
            raise ValueError("invalid tool message")

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


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次完整的四角色模型请求。"""

    model: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("ModelRequest requires model")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if not self.messages or self.messages[0].role != "system":
            raise ValueError("ModelRequest messages must start with system")
        if any(message.role == "system" for message in self.messages[1:]):
            raise ValueError("ModelRequest permits only one leading system message")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("ModelRequest Tool names must be unique")


class Model(Protocol):
    """AgentTree 循环使用的唯一模型端口。"""

    async def complete(self, request: ModelRequest) -> ChatMessage: ...
