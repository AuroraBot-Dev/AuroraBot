"""四角色聊天、模型与工具的最小公共契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from src.contracts.data import freeze_object
from src.contracts.evidence import freeze_evidence_refs
from src.contracts.resource import fixed_resource_refs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.resource import ResourceRef
    from src.contracts.tool import ToolDefinition

ChatRole = Literal["system", "message", "assistant", "tool"]


class ContextBudgetError(ValueError):
    """必要的身份、任务输入和恢复状态超过上下文容量。"""


@dataclass(frozen=True, slots=True)
class ToolContext:
    """由运行环境注入的调用归属与因果，模型不能通过工具参数设置。"""

    bot_id: str
    tree_id: str
    node_id: str
    caused_by: str | None = None

    def __post_init__(self) -> None:
        """调用上下文必须能唯一定位主体、认知树与节点。"""
        if not all(value.strip() for value in (self.bot_id, self.tree_id, self.node_id)):
            raise ValueError("工具上下文需要主体、认知树与节点身份")


@dataclass(frozen=True, slots=True)
class ToolCall:
    """assistant 请求的一次工具调用。"""

    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    context: ToolContext | None = None

    def __post_init__(self) -> None:
        """固定完整调用参数，环境适配器不能修改认知树中的原始提案。"""
        if not self.call_id or not self.name:
            raise ValueError("ToolCall requires call_id and name")
        object.__setattr__(self, "arguments", freeze_object(self.arguments))


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """AgentTree 内部使用的四角色消息。"""

    role: ChatRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    is_error: bool = False
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "evidence_refs", freeze_evidence_refs(self.evidence_refs))
        if self.evidence_refs and self.role not in {"message", "tool"}:
            raise ValueError("只有世界输入和工具结果可以声明原始证据来源")
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
    def message(cls, content: str, *, evidence_refs: tuple[str, ...] = ()) -> ChatMessage:
        """环境提供来源，模型只看到对应的可读内容。"""
        return cls("message", content, evidence_refs=evidence_refs)

    @classmethod
    def assistant(cls, content: str = "", *, tool_calls: tuple[ToolCall, ...] = ()) -> ChatMessage:
        return cls("assistant", content, tool_calls)

    @classmethod
    def tool(
        cls, call_id: str, content: str, *, is_error: bool = False, evidence_refs: tuple[str, ...] = ()
    ) -> ChatMessage:
        """保留工具结果声明的来源，不让模型通过正文伪造引用元数据。"""
        return cls("tool", content, tool_call_id=call_id, is_error=is_error, evidence_refs=evidence_refs)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次完整的四角色模型请求。"""

    model: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()
    resources: tuple[ResourceRef, ...] = ()

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("ModelRequest requires model")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "resources", fixed_resource_refs(self.resources))
        if not self.messages or self.messages[0].role != "system":
            raise ValueError("ModelRequest messages must start with system")
        if any(message.role == "system" for message in self.messages[1:]):
            raise ValueError("ModelRequest permits only one leading system message")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("ModelRequest Tool names must be unique")
