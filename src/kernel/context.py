"""能力目录：构造期可写上下文与冻结后的只读 ``Assembly``。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from src.contracts import ContributionKey, Settings


class Capabilities(Protocol):
    """只读能力视图：按契约类型读取实例与贡献。"""

    settings: Settings

    def get[T](self, capability: type[T]) -> T: ...

    def get_optional[T](self, capability: type[T]) -> T | None: ...

    def contains(self, capability: type) -> bool: ...

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]: ...


class ModuleContext(Capabilities, Protocol):
    """构造期上下文：在只读能力视图之上登记本模块产出。"""

    def provide[T](self, capability: type[T], instance: T) -> None: ...

    def contribute[T](self, key: ContributionKey[T], value: T) -> None: ...


@dataclass(frozen=True, slots=True)
class Assembly:
    """组合完成后的只读产物：配置入口与全部已构造能力。"""

    settings: Settings
    _instances: Mapping[type, object]
    _contributions: Mapping[str, tuple[object, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_instances", MappingProxyType(dict(self._instances)))
        object.__setattr__(self, "_contributions", MappingProxyType(dict(self._contributions)))

    def get[T](self, capability: type[T]) -> T:
        try:
            return cast("T", self._instances[capability])
        except KeyError as error:
            raise LookupError(f"能力尚未提供：{capability.__name__}") from error

    def get_optional[T](self, capability: type[T]) -> T | None:
        return cast("T | None", self._instances.get(capability))

    def contains(self, capability: type) -> bool:
        return capability in self._instances

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]:
        return cast("tuple[T, ...]", self._contributions.get(key.name, ()))

    @property
    def capabilities(self) -> tuple[type, ...]:
        return tuple(self._instances)


@dataclass(slots=True)
class _MutableContext:
    settings: Settings
    _instances: dict[type, object] = field(default_factory=dict)
    _contributions: dict[str, list[object]] = field(default_factory=dict)

    def contains(self, capability: type) -> bool:
        return capability in self._instances

    def get[T](self, capability: type[T]) -> T:
        try:
            return cast("T", self._instances[capability])
        except KeyError as error:
            raise LookupError(f"能力尚未提供：{capability.__name__}") from error

    def get_optional[T](self, capability: type[T]) -> T | None:
        return cast("T | None", self._instances.get(capability))

    def provide[T](self, capability: type[T], instance: T) -> None:
        if capability in self._instances:
            raise ValueError(f"能力重复提供：{capability.__name__}")
        self._instances[capability] = instance

    def contribute[T](self, key: ContributionKey[T], value: T) -> None:
        self._contributions.setdefault(key.name, []).append(value)

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]:
        return cast("tuple[T, ...]", tuple(self._contributions.get(key.name, ())))

    def seed(self, instances: Iterable[tuple[type, object]]) -> None:
        for capability, instance in instances:
            self.provide(capability, instance)

    def seed_contributions(self, values: Iterable[tuple[ContributionKey[object], object]]) -> None:
        for key, value in values:
            self.contribute(key, value)

    def freeze(self) -> Assembly:
        contributions = {name: tuple(values) for name, values in self._contributions.items()}
        return Assembly(self.settings, self._instances, contributions)
