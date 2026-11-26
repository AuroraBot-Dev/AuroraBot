"""由上下文活动与静默衰减决定随机判断窗口；仅保存本进程的调度状态。"""

import math
from collections.abc import Callable


class CadenceRhythm:
    def __init__(self, config: dict, now: float, uniform: Callable[[float, float], float]) -> None:
        self.active = config["active_seconds"]
        self.idle = config["idle_seconds"]
        self.half_life = config["half_life_seconds"]
        self.jitter = config["jitter_ratio"]
        self.uniform = uniform
        self.activity = 0.0
        self.updated_at = now
        self.last_started: float | None = None
        self.deadline = math.inf
        self.feedback = 0.5
        self.stimulate(now)

    def _decay(self, now: float) -> None:
        self.activity *= 2 ** (-max(0.0, now - self.updated_at) / self.half_life)
        if self.activity < 0.01:
            self.activity = 0.0
        self.updated_at = now

    def _delay(self) -> float:
        center = self.idle + (self.active - self.idle) * self.activity
        low, high = max(self.active, center * (1 - self.jitter)), max(self.active, center * (1 + self.jitter))
        delay = self.uniform(low, high)
        if not math.isfinite(delay) or not low <= delay <= high:
            raise ValueError("cadence 随机间隔超出节律窗口")
        return delay

    def stimulate(self, now: float, *, feedback: bool = False) -> bool:
        """外部变化补充刺激，内部反馈逐次减半；只提前期限，不推迟判断。"""
        self._decay(now)
        if feedback:
            strength = self.feedback
            self.feedback *= 0.5
            if strength < 0.01:
                return False
        else:
            strength = 1.0
            self.feedback = 0.5
        self.activity += (1 - self.activity) * 0.95 * strength
        earliest = now if self.last_started is None else self.last_started + self.active
        candidate = max(earliest, now + self._delay())
        previous = self.deadline
        self.deadline = min(previous, candidate)
        return self.deadline < previous

    def begin(self, now: float) -> None:
        self._decay(now)
        self.last_started = now
        self.deadline = math.inf

    def finish(self, now: float) -> None:
        """保留推理期间新刺激提出的期限，安静时按衰减后的窗口继续检查。"""
        self._decay(now)
        self.deadline = min(self.deadline, now + self._delay())
