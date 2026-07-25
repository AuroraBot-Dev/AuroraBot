"""Agent 发出的动作请求：委派、工具调用、完成和子 Agent 结果。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """Agent 发出的委派请求。"""

    instruction: str
    profile_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Agent 发出的工具调用请求。"""

    capability: str
    parameters: dict[str, Any]
    complete_task: bool = False
    tool_call_id: str | None = None
    continuation: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    """Agent 的完成声明：摘要、产出物和静默标记。"""

    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    silent: bool = False


@dataclass(frozen=True, slots=True)
class ChildResult:
    """子 Agent 完成后的结果报告。"""

    child_agent_id: str
    status: Literal["completed", "failed"]
    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
