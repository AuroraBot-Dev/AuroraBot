"""工具执行、绑定与回执契约（工具域统一与 AMP 化回执）。

工具结果统一经 AMP（``tool.{status}``）回 engine：executor 只负责执行并
通过 ``tool_receipt_amp`` 构造回执提交，engine 不再有内部完成端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from src.contracts.amp import new_amp

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor

MEMORY_REMEMBER_CAPABILITY = "aur.serv.memory.remember"
"""主动记忆写入工具 ID（服务域命名）：agents 侧能力与 memory 侧执行器的跨层线缆契约。"""

_TOOL_STATUSES = frozenset({"succeeded", "failed", "unknown"})

TOOL_EVENT_TYPES = frozenset({f"tool.{status}" for status in _TOOL_STATUSES})
"""工具回执事件类型全集（``tool.succeeded`` / ``tool.failed`` / ``tool.unknown``）。

engine 摄入分拣、agent 恢复与平台保留事件的唯一来源。
"""


class _Msg(StrEnum):
    INVALID_STATUS = "tool receipt status must be succeeded, failed or unknown"
    SUCCESS_WITH_ERROR = "a succeeded tool receipt cannot contain an error"
    FAILURE_WITHOUT_ERROR = "a failed or unknown tool receipt requires error and forbids result"


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    """平台工具执行请求。"""

    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


class ToolExecutor(Protocol):
    """执行单个外部工具请求：执行完成后通过注入的 AMP 入口提交 tool.{status} 回执。"""

    async def execute_tool(self, request: ToolExecutionRequest) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolExecutorBinding:
    """能力描述符与具体平台执行器的组合绑定（一对一路由表条目）。"""

    capability: CapabilityDescriptor
    executor: ToolExecutor
    source_app: str
    source_instance: str


def tool_receipt_amp(
    *,
    status: str,
    request: ToolExecutionRequest,
    summary: str,
    source_app: str,
    source_instance: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """构造工具回执 AMP：executor 执行完成后提交此信封。"""
    if status not in _TOOL_STATUSES:
        raise ValueError(_Msg.INVALID_STATUS)
    if status == "succeeded" and error is not None:
        raise ValueError(_Msg.SUCCESS_WITH_ERROR)
    if status != "succeeded" and (not error or result is not None):
        raise ValueError(_Msg.FAILURE_WITHOUT_ERROR)
    return new_amp(
        event_type=f"tool.{status}",
        session_id=request.session_id,
        summary=summary,
        data={
            "request_id": request.request_id,
            "capability": request.capability,
            "result": result,
            "error": error,
        },
        source_app=source_app,
        source_instance=source_instance,
    ).to_dict()
