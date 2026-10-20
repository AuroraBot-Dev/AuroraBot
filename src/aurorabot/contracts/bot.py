"""Bot 持续拥有的目标、恢复依据和未来活动安排。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from aurorabot.contracts.identity import Identifier

if TYPE_CHECKING:
    from datetime import datetime


class GoalStatus(StrEnum):
    """Bot 对一项目标的当前选择。"""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class WakeStatus(StrEnum):
    """一次持久唤醒安排的交付结果。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class StateConflictError(ValueError):
    """提交基于过期状态，需要重新读取并判断。"""


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """恢复工作所需的显式状态；只保存结果、约束与证据。"""

    stage: str = ""
    confirmed: tuple[str, ...] = ()
    pending_actions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """固定集合并拒绝空白条目。"""
        for name in ("confirmed", "pending_actions", "constraints", "open_questions", "evidence_refs"):
            values = tuple(getattr(self, name))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"检查点 {name} 必须由非空文本组成")
            object.__setattr__(self, name, values)


@dataclass(frozen=True, slots=True)
class Goal:
    """Bot 接受、修订或结束的一项目标，与认知树独立存续。"""

    goal_id: str
    purpose: str
    success_condition: str
    status: GoalStatus = GoalStatus.ACTIVE
    checkpoint: Checkpoint = field(default_factory=Checkpoint)

    def __post_init__(self) -> None:
        """验证目标身份、完成条件与状态。"""
        identifier = Identifier.parse(self.goal_id)
        if not identifier.path.startswith("goal/"):
            raise ValueError("目标身份必须形如 <namespace>:goal/<name>")
        if not self.purpose.strip() or not self.success_condition.strip():
            raise ValueError("目标的意图与完成条件不能为空")
        if not isinstance(self.status, GoalStatus):
            raise TypeError("目标状态必须是 GoalStatus")


@dataclass(frozen=True, slots=True)
class WakePlan:
    """Bot 选择的一次未来检查；运行身份在安排时固定。"""

    wake_id: str
    due_at: datetime
    message: str
    goal_id: str | None = None
    status: WakeStatus = WakeStatus.PENDING
    detail: str = ""

    def __post_init__(self) -> None:
        """验证持久时间、唤醒身份与目标引用。"""
        identifier = Identifier.parse(self.wake_id)
        if not identifier.path.startswith("wake/"):
            raise ValueError("唤醒身份必须形如 <namespace>:wake/<name>")
        if self.due_at.tzinfo is None or self.due_at.utcoffset() is None:
            raise ValueError("唤醒时间必须包含时区")
        if not self.message.strip():
            raise ValueError("唤醒意图不能为空")
        if self.goal_id is not None:
            Identifier.parse(self.goal_id)
        if not isinstance(self.status, WakeStatus):
            raise TypeError("唤醒状态必须是 WakeStatus")


@dataclass(frozen=True, slots=True)
class BotSnapshot:
    """一个 Bot 在确定版本上的不可变主体状态。"""

    bot_id: str
    version: int = 0
    goals: tuple[Goal, ...] = ()
    wakes: tuple[WakePlan, ...] = ()

    def __post_init__(self) -> None:
        """固定状态集合并校验版本与身份唯一性。"""
        Identifier.parse(self.bot_id)
        object.__setattr__(self, "goals", tuple(self.goals))
        object.__setattr__(self, "wakes", tuple(self.wakes))
        if self.version < 0:
            raise ValueError("Bot 状态版本不能小于零")
        if len({item.goal_id for item in self.goals}) != len(self.goals):
            raise ValueError("目标身份不能重复")
        if len({item.wake_id for item in self.wakes}) != len(self.wakes):
            raise ValueError("唤醒身份不能重复")

    def goal(self, goal_id: str) -> Goal:
        """取得一项目标，缺失时明确失败。"""
        for goal in self.goals:
            if goal.goal_id == goal_id:
                return goal
        raise LookupError(f"目标不存在：{goal_id}")

    def wake(self, wake_id: str) -> WakePlan:
        """取得一次唤醒安排，缺失时明确失败。"""
        for wake in self.wakes:
            if wake.wake_id == wake_id:
                return wake
        raise LookupError(f"唤醒安排不存在：{wake_id}")


@dataclass(frozen=True, slots=True)
class BotChange:
    """基于显式版本原子修改目标与安排，可用命令身份重试。"""

    command_id: str
    expected_version: int
    goals: tuple[Goal, ...] = ()
    wakes: tuple[WakePlan, ...] = ()

    def __post_init__(self) -> None:
        """校验修改内容和幂等身份。"""
        object.__setattr__(self, "goals", tuple(self.goals))
        object.__setattr__(self, "wakes", tuple(self.wakes))
        if not self.command_id.strip() or self.expected_version < 0:
            raise ValueError("状态修改需要非空命令身份和非负版本")
        if not self.goals and not self.wakes:
            raise ValueError("状态修改不能为空")
        if len({item.goal_id for item in self.goals}) != len(self.goals):
            raise ValueError("一次修改不能重复声明同一目标")
        if len({item.wake_id for item in self.wakes}) != len(self.wakes):
            raise ValueError("一次修改不能重复声明同一唤醒")
