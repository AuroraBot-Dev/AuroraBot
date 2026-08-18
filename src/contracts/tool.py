"""工具定义、执行结果与效果端口契约。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.model import ToolCall


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """模型可见的工具定义。"""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.name or not self.description:
            raise ValueError("ToolDefinition requires name and description")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """工具调用的一次规范化文本结果。"""

    content: str
    is_error: bool = False

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("ToolOutput content must not be empty")


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """工具请求 engine 创建一个 child Agent。"""

    agent: str
    instruction: str

    def __post_init__(self) -> None:
        if not self.agent.strip() or not self.instruction.strip():
            raise ValueError("DelegationRequest requires agent and instruction")


type ToolResult = ToolOutput | DelegationRequest


class Tool(Protocol):
    """工具域中可注册、可路由的统一效果端口。"""

    @property
    def definition(self) -> ToolDefinition: ...

    async def execute(self, call: ToolCall) -> ToolResult: ...
