"""工具定义、执行结果与效果端口契约。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from src.contracts.data import freeze_object
from src.contracts.evidence import freeze_evidence_refs
from src.contracts.resource import ResourceRef
from src.contracts.tool_resource import tool_content, tool_resource_key

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.model import ToolCall


class ToolStatus(StrEnum):
    """一次工具调用的确定性结果状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """模型可见的工具定义。"""

    name: str
    description: str
    parameters: Mapping[str, Any]
    content: bytes = field(init=False, repr=False)
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        """工具参数声明使用不可变 JSON，调用者不能改变已冻结目录。"""
        if not self.name or not self.description:
            raise ValueError("ToolDefinition 需要非空名称与说明")
        key = tool_resource_key(self.name)
        object.__setattr__(self, "parameters", freeze_object(self.parameters))
        content = tool_content(self)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "ref", ResourceRef(key, hashlib.sha256(content).hexdigest()))


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """工具调用的一次规范化文本结果。"""

    content: str
    status: ToolStatus = ToolStatus.SUCCEEDED
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("ToolOutput content must not be empty")
        object.__setattr__(self, "evidence_refs", freeze_evidence_refs(self.evidence_refs))
        if not isinstance(self.status, ToolStatus):
            raise TypeError("ToolOutput status must be a ToolStatus")

    @property
    def is_error(self) -> bool:
        """failed 与 unknown 都作为可供模型处理的错误消息。"""
        return self.status is not ToolStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """工具请求 engine 创建一个 child Agent。"""

    agent: str
    instruction: str

    def __post_init__(self) -> None:
        if not self.agent.strip() or not self.instruction.strip():
            raise ValueError("DelegationRequest requires agent and instruction")


type ToolResult = ToolOutput | DelegationRequest

DELEGATE_TOOL = "aurora:tool/definition/delegate"
WAIT_TOOL = "aurora:tool/definition/wait"
WORLD_READ_TOOL = "aurora:tool/definition/world_read"
WORLD_SCOPES_TOOL = "aurora:tool/definition/world_scopes"
WORLD_TREES_TOOL = "aurora:tool/definition/world_trees"

BUILTIN_TOOL_NAMES = frozenset({DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_SCOPES_TOOL, WORLD_TREES_TOOL})


class Tool(Protocol):
    """工具域中可注册、可路由的统一效果端口。"""

    @property
    def definition(self) -> ToolDefinition: ...

    async def execute(self, call: ToolCall) -> ToolResult: ...
