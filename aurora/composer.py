"""为项目组合根提供类型化实例注册与读取。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool


@dataclass(frozen=True, slots=True)
class InstanceKey[T]:
    """标识一个由组合模块导出的项目实例。"""

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("实例键名称不能为空")


@dataclass(frozen=True, slots=True)
class AuroraAssembly:
    """组合完成后的只读实例集合。"""

    _instances: Mapping[InstanceKey[object], object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_instances", MappingProxyType(dict(self._instances)))

    def get[T](self, key: InstanceKey[T]) -> T:
        try:
            instance = self._instances[cast("InstanceKey[object]", key)]
        except KeyError as error:
            raise KeyError(f"实例尚未注册：{key.name}") from error
        return cast("T", instance)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(key.name for key in self._instances)


@dataclass(slots=True)
class CompositionContext:
    """向各组合模块提供配置、外部端口和已构造实例。"""

    config: AuroraConfig
    model: Model | None
    tools: tuple[Tool, ...]
    _instances: dict[InstanceKey[object], object] = field(default_factory=dict)
    _names: set[str] = field(default_factory=set)

    def contains[T](self, key: InstanceKey[T]) -> bool:
        """返回一个分阶段预构造实例是否已经进入组合上下文。"""
        return key.name in self._names

    def provide[T](self, key: InstanceKey[T], instance: T) -> None:
        if key.name in self._names:
            raise ValueError(f"实例重复注册：{key.name}")
        self._names.add(key.name)
        self._instances[cast("InstanceKey[object]", key)] = instance

    def require[T](self, key: InstanceKey[T]) -> T:
        try:
            instance = self._instances[cast("InstanceKey[object]", key)]
        except KeyError as error:
            raise KeyError(f"组合依赖尚未注册：{key.name}") from error
        return cast("T", instance)

    def finish(self) -> AuroraAssembly:
        return AuroraAssembly(self._instances)


type CompositionRegistrar = Callable[[CompositionContext], None]
type InstanceBinding = tuple[InstanceKey[object], object]


def compose(
    config: AuroraConfig,
    model: Model | None,
    registrars: Iterable[CompositionRegistrar],
    tools: Iterable[Tool] = (),
    instances: Iterable[InstanceBinding] = (),
) -> AuroraAssembly:
    """按显式注册顺序构造所有项目实例。"""
    context = CompositionContext(config, model, tuple(tools))
    for key, instance in instances:
        context.provide(key, instance)
    for register in registrars:
        register(context)
    return context.finish()
