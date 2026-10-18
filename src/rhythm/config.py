"""节律策略选择与模型推理参数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.contracts.model_artifact import model_weight_reference
from src.contracts.resource import ResourceKey

if TYPE_CHECKING:
    from src.contracts.resource import ResourceRef


@dataclass(frozen=True, slots=True)
class RhythmConfig:
    """基线参数和学习模型路径各自有明确用途。"""

    policy: str = "aurora:rhythm/model/rules"
    weights: str | None = None
    evoke_every: int = 1
    max_idle_seconds: float = 3600
    min_check_seconds: float = 1
    probability_threshold: float = 0.5
    weights_ref: str | None = None

    def __post_init__(self) -> None:
        """只接收节律模型资源，期限和概率保持有效。"""
        key = ResourceKey.parse(self.policy)
        if (key.domain, key.kind) != ("rhythm", "model"):
            raise ValueError("节律策略必须引用 rhythm/model 资源")
        if self.evoke_every <= 0 or not 0 < self.min_check_seconds <= self.max_idle_seconds:
            raise ValueError("节律阈值与检查间隔无效")
        if not 0 < self.probability_threshold < 1:
            raise ValueError("节律概率阈值必须位于零到一之间")
        model_weight_reference(key, self.weights, self.weights_ref)

    @property
    def reference(self) -> ResourceRef | None:
        """返回已经校验的具体模型资源版本。"""
        return model_weight_reference(ResourceKey.parse(self.policy), self.weights, self.weights_ref)
