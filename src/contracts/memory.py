"""记忆读取的显式任务条件和历史可见边界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.contracts.identity import Identifier

if TYPE_CHECKING:
    from datetime import datetime

    from src.contracts.bot import Goal, WakePlan


@dataclass(frozen=True, slots=True)
class MemoryContinuity:
    """本次工作所需的完整状态，以及未展开主体内容的明确概览。"""

    bot_id: str
    version: int
    goals: tuple[Goal, ...] = ()
    wakes: tuple[WakePlan, ...] = ()
    goal_counts: tuple[tuple[str, int], ...] = ()
    wake_counts: tuple[tuple[str, int], ...] = ()
    missing_goal_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryRequest:
    """在确定的获知边界内，为当前任务选择经历。"""

    query: str = ""
    focus_goal_ids: tuple[str, ...] = ()
    scopes: frozenset[str] | None = None
    cursor: int | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        """固定任务条件，拒绝无效时间和不明确的目标身份。"""
        goals = tuple(self.focus_goal_ids)
        if len(set(goals)) != len(goals):
            raise ValueError("记忆读取的焦点目标不能重复")
        for goal in goals:
            if not Identifier.parse(goal).path.startswith("goal/"):
                raise ValueError("记忆焦点必须引用目标")
        if self.cursor is not None and self.cursor < 0:
            raise ValueError("记忆读取游标不能小于零")
        if self.observed_at is not None and (self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None):
            raise ValueError("记忆读取时间必须包含时区")
        if self.scopes is not None:
            scopes = frozenset(self.scopes)
            if any(not scope.strip() for scope in scopes):
                raise ValueError("记忆读取域不能为空")
            object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "focus_goal_ids", goals)
