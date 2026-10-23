"""可与学习模型直接比较的确定节律基线。"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import TYPE_CHECKING

from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.contracts.rhythm import RhythmAction, RhythmDecision, RhythmPrediction

if TYPE_CHECKING:
    from aurora_bot.contracts.rhythm import RhythmObservation


class RuleRhythmPolicy:
    """按事件压力、即时路由和最长安静时间分配推理机会。"""

    def __init__(self, *, evoke_every: int = 5, max_idle_seconds: float = 3600) -> None:
        """阈值构成基线策略参数，调度器不解释这些参数。"""
        if evoke_every <= 0:
            raise ValueError("evoke_every 必须大于零")
        if not math.isfinite(max_idle_seconds) or max_idle_seconds <= 0:
            raise ValueError("max_idle_seconds 必须是有限正数")
        self.evoke_every = evoke_every
        self.max_idle_seconds = max_idle_seconds

    @property
    def ref(self) -> ResourceRef:
        """基线策略也有可审计的版本身份。"""
        return ResourceRef(ResourceKey.parse("aurora:rhythm/model/rules"), "1")

    @property
    def parameters(self) -> dict[str, float | int]:
        """基线参数随每次判断进入持久记录。"""
        return {"evoke_every": self.evoke_every, "max_idle_seconds": self.max_idle_seconds}

    def evaluate(self, observation: RhythmObservation, hidden: tuple[float, ...] = ()) -> RhythmPrediction:
        """等待结果和唤醒结果共享同一契约。"""
        if hidden:
            raise ValueError("规则策略不接受循环隐状态")
        if observation.reactive_event:
            reason = "即时事件值得获得一次理解机会"
        elif observation.pending_events >= self.evoke_every:
            reason = "待理解事件达到当前注意力阈值"
        elif observation.timer_due or observation.elapsed_seconds >= self.max_idle_seconds:
            reason = "到达主动观察时间"
        else:
            remaining = max(0.001, self.max_idle_seconds - observation.elapsed_seconds)
            decision = RhythmDecision(
                RhythmAction.WAIT,
                observation.observed_at + timedelta(seconds=remaining),
                "继续积累变化并等待下一次检查",
                observation.active_goal_ids,
            )
            return RhythmPrediction(decision)
        decision = RhythmDecision(
            RhythmAction.DELIBERATE,
            observation.observed_at + timedelta(seconds=self.max_idle_seconds),
            reason,
            observation.active_goal_ids,
            1.0,
        )
        return RhythmPrediction(decision)
