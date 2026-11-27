"""模型适配器目录与带类型的实例工厂。"""

from dataclasses import dataclass

from aurora_core.ids import Id

from .contract import ModelFactory, ModelKind

ADAPTERS = Id("org.aurora.model:registries/adapters")


@dataclass(frozen=True)
class ModelAdapter[T]:
    """同一注册表中的类型化工厂，防止聊天、决策与向量角色混用。"""

    kind: ModelKind
    factory: ModelFactory[T]
