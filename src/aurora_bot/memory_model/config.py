"""记忆推荐策略和模型权重的独立配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora_bot.contracts.model_artifact import model_weight_reference
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.utils.validation import check_positive_number

if TYPE_CHECKING:
    from aurora_bot.contracts.resource import ResourceRef


@dataclass(frozen=True, slots=True)
class MemoryModelConfig:
    """同一套记忆读写环境可以替换排序策略。"""

    policy: str = "aurora:memory/model/rules"
    weights: str | None = None
    checkpoint_seconds: float = 60.0
    weights_ref: str | None = None

    def __post_init__(self) -> None:
        """只接受记忆模型资源，具体版本由权重内容确定。"""
        key = ResourceKey.parse(self.policy)
        if (key.domain, key.kind) != ("memory", "model"):
            raise ValueError("记忆推荐策略必须引用 memory/model 资源")
        check_positive_number(self.checkpoint_seconds, "memory_model.checkpoint_seconds")
        model_weight_reference(key, self.weights, self.weights_ref)

    @property
    def reference(self) -> ResourceRef | None:
        """返回与策略身份相同的固定内容版本。"""
        return model_weight_reference(ResourceKey.parse(self.policy), self.weights, self.weights_ref)
