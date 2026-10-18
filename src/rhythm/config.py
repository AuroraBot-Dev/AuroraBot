"""节律策略选择与模型推理参数。"""

from dataclasses import dataclass

from src.contracts.resource import ResourceKey


@dataclass(frozen=True, slots=True)
class RhythmConfig:
    """基线参数和学习模型路径各自有明确用途。"""

    policy: str = "aurora:rhythm/model/rules"
    weights: str | None = None
    evoke_every: int = 1
    max_idle_seconds: float = 3600
    min_check_seconds: float = 1
    probability_threshold: float = 0.5

    def __post_init__(self) -> None:
        """只接收节律模型资源，期限和概率保持有效。"""
        key = ResourceKey.parse(self.policy)
        if (key.domain, key.kind) != ("rhythm", "model"):
            raise ValueError("节律策略必须引用 rhythm/model 资源")
        if self.evoke_every <= 0 or not 0 < self.min_check_seconds <= self.max_idle_seconds:
            raise ValueError("节律阈值与检查间隔无效")
        if not 0 < self.probability_threshold < 1:
            raise ValueError("节律概率阈值必须位于零到一之间")
