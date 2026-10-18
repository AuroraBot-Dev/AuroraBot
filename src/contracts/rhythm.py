"""节律策略的可观察输入、显式循环状态与推理机会。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts.identity import Identifier

if TYPE_CHECKING:
    from datetime import datetime

RHYTHM_FEATURES = (
    "pending_events",
    "elapsed_seconds",
    "active_goals",
    "pending_actions",
    "failed_wakes",
    "timer_due",
    "reactive_event",
    "hour_sin",
    "hour_cos",
)
_SECONDS_PER_DAY = 86_400


class RhythmAction(StrEnum):
    """节律只分配推理机会，实际行动仍由 Bot 决定。"""

    WAIT = "wait"
    DELIBERATE = "deliberate"


@dataclass(frozen=True, slots=True)
class RhythmObservation:
    """不调用 LLM 即可获得的环境与主体特征。"""

    bot_id: str
    observed_at: datetime
    cursor: int
    pending_events: int
    elapsed_seconds: float
    active_goal_ids: tuple[str, ...] = ()
    pending_actions: int = 0
    failed_wakes: int = 0
    timer_due: bool = False
    reactive_event: bool = False

    def __post_init__(self) -> None:
        """拒绝无时区时间、负计数及非有限时长。"""
        if not Identifier.parse(self.bot_id).path.startswith("bot/"):
            raise ValueError("节律观察必须属于一个 Bot")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("节律观察时间必须包含时区")
        if min(self.cursor, self.pending_events, self.pending_actions, self.failed_wakes) < 0:
            raise ValueError("节律计数不能小于零")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("节律时长必须是有限非负数")
        object.__setattr__(self, "active_goal_ids", tuple(self.active_goal_ids))

    def features(self) -> tuple[float, ...]:
        """在线推理与训练共用确定的特征顺序和数值变换。"""
        utc_seconds = self.observed_at.timestamp() % _SECONDS_PER_DAY
        phase = math.tau * utc_seconds / _SECONDS_PER_DAY
        return (
            math.log1p(self.pending_events),
            math.log1p(self.elapsed_seconds),
            math.log1p(len(self.active_goal_ids)),
            math.log1p(self.pending_actions),
            math.log1p(self.failed_wakes),
            float(self.timer_due),
            float(self.reactive_event),
            math.sin(phase),
            math.cos(phase),
        )


@dataclass(frozen=True, slots=True)
class RhythmDecision:
    """思考或等待，以及下一次检查的绝对时间。"""

    action: RhythmAction
    next_check_at: datetime
    reason: str
    focus_goal_ids: tuple[str, ...] = ()
    probability: float = 0.0

    def __post_init__(self) -> None:
        """决策必须可解释，概率与时间不得含混。"""
        if not isinstance(self.action, RhythmAction) or not self.reason.strip():
            raise ValueError("节律决策需要明确动作与原因")
        if self.next_check_at.tzinfo is None or self.next_check_at.utcoffset() is None:
            raise ValueError("下一次检查时间必须包含时区")
        if not 0 <= self.probability <= 1:
            raise ValueError("节律概率必须位于零到一之间")
        object.__setattr__(self, "focus_goal_ids", tuple(self.focus_goal_ids))


@dataclass(frozen=True, slots=True)
class RhythmPrediction:
    """策略输出和可持久化的下一循环隐状态。"""

    decision: RhythmDecision
    hidden: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        """固定状态向量并拒绝无法恢复的数值。"""
        values = tuple(self.hidden)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("节律隐状态必须由有限数值组成")
        object.__setattr__(self, "hidden", values)
