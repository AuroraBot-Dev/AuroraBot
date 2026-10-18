"""记忆推荐策略和模型权重的独立配置。"""

from dataclasses import dataclass

from src.contracts.resource import ResourceKey


@dataclass(frozen=True, slots=True)
class MemoryModelConfig:
    """同一套记忆读写环境可以替换排序策略。"""

    policy: str = "aurora:memory/model/rules"
    weights: str | None = None

    def __post_init__(self) -> None:
        """只接受记忆模型资源，具体版本由权重内容确定。"""
        key = ResourceKey.parse(self.policy)
        if (key.domain, key.kind) != ("memory", "model"):
            raise ValueError("记忆推荐策略必须引用 memory/model 资源")
