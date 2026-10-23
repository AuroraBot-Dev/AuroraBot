"""只读执行状态、事件和最终结果。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora_agent.contracts import ToolOutput, Usage
    from aurora_agent.messages import ChatMessage, ToolCall


class RunStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LIMIT_REACHED = "limit_reached"

    @property
    def terminal(self) -> bool:
        return self not in {RunStatus.READY, RunStatus.RUNNING}


class CallStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CallRecord:
    call: ToolCall
    status: CallStatus = CallStatus.PENDING
    output: ToolOutput | None = None


@dataclass(frozen=True, slots=True)
class RunStats:
    model_calls: int = 0
    tool_calls: int = 0
    usage: Usage | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    status: RunStatus
    output: str | None
    reason: str | None
    stats: RunStats


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: str
    status: RunStatus
    messages: tuple[ChatMessage, ...]
    queued_messages: tuple[ChatMessage, ...]
    calls: tuple[CallRecord, ...]
    stats: RunStats
    cancel_requested: bool
    result: RunResult | None


class EventKind(StrEnum):
    CREATED = "created"
    MESSAGE_QUEUED = "message_queued"
    MESSAGES_APPLIED = "messages_applied"
    MODEL_STARTED = "model_started"
    MODEL_COMPLETED = "model_completed"
    TOOL_PROPOSED = "tool_proposed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_UNKNOWN = "tool_unknown"
    CANCEL_REQUESTED = "cancel_requested"
    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class RunEvent:
    """事件只携带进度元数据；正文与参数通过显式快照读取。"""

    sequence: int
    run_id: str
    kind: EventKind
    status: RunStatus
    call_id: str | None = None
