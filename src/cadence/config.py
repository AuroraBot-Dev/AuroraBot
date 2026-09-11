"""``src.cadence`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    """世界提交驱动的节律策略。"""

    enabled: bool
    agent: str
    evoke_every: int
    tick_seconds: int
    poll_seconds: float
