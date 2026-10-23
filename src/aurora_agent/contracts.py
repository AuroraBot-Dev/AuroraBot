"""Agent 的输入、模型和工具端口；不含宿主身份或执行拓扑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from aurora_agent.data import freeze_object
from aurora_agent.messages import ChatMessage, ToolCall, validate_history

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurora_agent.state import RunSnapshot


class ContextBudgetError(ValueError):
    """必要上下文超过预算，尚未调用模型。"""


class ModelError(RuntimeError):
    """模型适配器报告的预期失败。"""


class ToolExecutionError(RuntimeError):
    """工具明确确认失败；不会被用来表示效果未知。"""


class ToolEffectUnknownError(RuntimeError):
    """工具可能已产生效果，必须停止运行并由宿主核对。"""


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.description.strip():
            raise ValueError("工具需要非空名称和描述")
        object.__setattr__(self, "parameters", freeze_object(self.parameters))


@dataclass(frozen=True, slots=True)
class ToolOutput:
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolContext:
    """宿主注入的调用归属，不接受模型通过参数伪造。"""

    run_id: str
    call_id: str


class Tool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput: ...


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("模型用量不能为负")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if not self.model.strip() or not self.messages or self.messages[0].role != "system":
            raise ValueError("模型请求需要明确模型身份和首条系统消息")
        validate_history(self.messages[1:])
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("模型请求不能包含重名工具")


@dataclass(frozen=True, slots=True)
class ModelResponse:
    message: ChatMessage
    usage: Usage | None = None

    def __post_init__(self) -> None:
        if self.message.role != "assistant":
            raise ValueError("模型必须返回 assistant 消息")


class Model(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResponse: ...


@dataclass(frozen=True, slots=True)
class RunLimits:
    max_model_calls: int = 32
    max_tool_calls: int = 128
    max_context_chars: int = 100_000

    def __post_init__(self) -> None:
        if self.max_model_calls < 1 or self.max_tool_calls < 0 or self.max_context_chars < 1:
            raise ValueError("模型和上下文上限必须为正，工具上限不能为负")


@dataclass(frozen=True, slots=True)
class RunRequest:
    message: str
    run_id: str | None = None
    history: tuple[ChatMessage, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "history", tuple(self.history))
        if not self.message.strip() or (self.run_id is not None and not self.run_id.strip()):
            raise ValueError("任务与运行身份不能为空")
        validate_history(self.history)


@dataclass(frozen=True, slots=True)
class ContextInput:
    run_id: str
    instructions: str
    model: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...]


class ContextAssembler(Protocol):
    async def assemble(self, context: ContextInput) -> tuple[ChatMessage, ...]: ...


class ToolAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    RECONSIDER = "reconsider"


@dataclass(frozen=True, slots=True)
class ToolDecision:
    """RECONSIDER 以错误结果结束尚未执行的调用，让模型依据新信息重新提案。"""

    action: ToolAction = ToolAction.ALLOW
    content: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.action, ToolAction):
            raise TypeError("行动决定需要 ToolAction")
        if self.action != ToolAction.ALLOW and not self.content.strip():
            raise ValueError("拒绝或重新判断需要给模型的说明")


class ToolPolicy(Protocol):
    async def before_tool(self, snapshot: RunSnapshot, call: ToolCall) -> ToolDecision: ...
