"""SQL 状态字面量：从 contracts 枚举生成。

SQL 中 agents/mailbox/activities/tasks 的状态字面量一律引用本模块常量，
禁止手写；枚举改名或增删值时，编译期即可发现不一致。
inbox_events 的 PENDING/TRIAGING/DEFERRED 无对应契约枚举，保持字面量。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from src.contracts import (
    ActivityStatus,
    AgentStatus,
    MessageStatus,
    TaskStatus,
)


def _quoted(value: StrEnum) -> str:
    return f"'{value.value}'"


def _set(*values: StrEnum) -> str:
    return "(" + ", ".join(_quoted(item) for item in values) + ")"


# -- agent 状态 -----------------------------------------------------------

AGENT_READY: Final = _quoted(AgentStatus.READY)
AGENT_COMPLETED: Final = _quoted(AgentStatus.COMPLETED)
AGENT_FAILED: Final = _quoted(AgentStatus.FAILED)
AGENT_CANCELLED: Final = _quoted(AgentStatus.CANCELLED)
AGENT_TERMINAL: Final = _set(AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED)

# -- mailbox 消息状态 -----------------------------------------------------

MSG_PENDING: Final = _quoted(MessageStatus.PENDING)
MSG_PROCESSING: Final = _quoted(MessageStatus.PROCESSING)
MSG_COMPLETED: Final = _quoted(MessageStatus.COMPLETED)
MSG_ERROR: Final = _quoted(MessageStatus.ERROR)

# -- activity 状态 --------------------------------------------------------

ACT_PENDING: Final = _quoted(ActivityStatus.PENDING)
ACT_PROCESSING: Final = _quoted(ActivityStatus.PROCESSING)
ACT_COMPLETED: Final = _quoted(ActivityStatus.COMPLETED)
ACT_ERROR: Final = _quoted(ActivityStatus.ERROR)
ACT_CANCELLED: Final = _quoted(ActivityStatus.CANCELLED)
ACT_ACTIVE: Final = _set(ActivityStatus.PENDING, ActivityStatus.PROCESSING)
ACT_NONCANCELLED: Final = _set(
    ActivityStatus.PENDING,
    ActivityStatus.PROCESSING,
    ActivityStatus.COMPLETED,
    ActivityStatus.ERROR,
)

# -- task 状态 ------------------------------------------------------------

TASK_ACTIVE: Final = _quoted(TaskStatus.ACTIVE)
