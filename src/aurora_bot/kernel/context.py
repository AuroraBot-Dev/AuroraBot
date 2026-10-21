"""Bot 能力目录：固定声明索引与宿主管理的共享 ctx。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol, cast

from aurora_kernel import Context

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from aurora_bot.contracts import ContributionKey, Settings
    from aurora_bot.kernel.declaration import ModuleSpec


def capability_name(capability: type) -> str:
    """仅在 Bot 适配边界把既有 Python 契约转换成宿主键。"""
    return f"python:{capability.__module__}.{capability.__qualname__}"


class Capabilities(Protocol):
    """只读能力视图：按契约类型读取实例与贡献。"""

    @property
    def ctx(self) -> Context: ...

    @property
    def settings(self) -> Settings: ...

    @property
    def modules(self) -> tuple[ModuleSpec, ...]: ...

    def get[T](self, capability: type[T]) -> T: ...

    def get_optional[T](self, capability: type[T]) -> T | None: ...

    def contains(self, capability: type) -> bool: ...

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]: ...


class ModuleContext(Capabilities, Protocol):
    """构造期上下文：在只读能力视图之上登记本模块产出。"""

    def provide[T](self, capability: type[T], instance: T) -> None: ...

    def contribute[T](self, key: ContributionKey[T], value: T) -> None: ...

    def is_provider(self, capability: type) -> bool:
        """当前模块是否被解析器选中来提供此能力。"""
        ...


@dataclass(frozen=True, slots=True)
class Assembly:
    """组合后的声明索引保持固定，能力与贡献从共享 ctx 实时读取。"""

    settings: Settings
    _instances: Mapping[type, object]
    _contributions: Mapping[str, tuple[object, ...]]
    modules: tuple[ModuleSpec, ...] = ()
    ctx: Context = field(default_factory=Context, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_instances", MappingProxyType(dict(self._instances)))
        object.__setattr__(self, "_contributions", MappingProxyType(dict(self._contributions)))
        object.__setattr__(self, "modules", tuple(self.modules))
        if "kernel.services" not in self.ctx:
            self.ctx.ensure("kernel.services").update(
                {capability_name(capability): instance for capability, instance in self._instances.items()}
            )
        if "kernel.contributions" not in self.ctx:
            self.ctx.ensure("kernel.contributions").update(self._contributions)

    def get[T](self, capability: type[T]) -> T:
        try:
            return cast("T", self.ctx["kernel.services"][capability_name(capability)])
        except KeyError as error:
            raise LookupError(f"能力尚未提供：{capability.__name__}") from error

    def get_optional[T](self, capability: type[T]) -> T | None:
        return cast("T | None", self.ctx["kernel.services"].get(capability_name(capability)))

    def contains(self, capability: type) -> bool:
        return capability_name(capability) in self.ctx["kernel.services"]

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]:
        return cast("tuple[T, ...]", tuple(self.ctx["kernel.contributions"].get(key.name, ())))

    @property
    def capabilities(self) -> tuple[type, ...]:
        return tuple(self._instances)


@dataclass(slots=True)
class _MutableContext:
    settings: Settings
    modules: tuple[ModuleSpec, ...] = ()
    ctx: Context = field(default_factory=Context, compare=False)
    _instances: dict[type, object] = field(default_factory=dict)
    _contributions: dict[str, list[object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.ctx.ensure("kernel.services")
        self.ctx.ensure("kernel.contributions")
        self.ctx.ensure("aurora.bot")["settings"] = self.settings

    def contains(self, capability: type) -> bool:
        return capability_name(capability) in self.ctx["kernel.services"]

    def is_provider(self, capability: type) -> bool:
        """底层容器接受显式种子，模块钩子通过受限视图访问。"""
        return True

    def get[T](self, capability: type[T]) -> T:
        try:
            return cast("T", self.ctx["kernel.services"][capability_name(capability)])
        except KeyError as error:
            raise LookupError(f"能力尚未提供：{capability.__name__}") from error

    def get_optional[T](self, capability: type[T]) -> T | None:
        return cast("T | None", self.ctx["kernel.services"].get(capability_name(capability)))

    def provide[T](self, capability: type[T], instance: T) -> None:
        if self.contains(capability):
            raise ValueError(f"能力重复提供：{capability.__name__}")
        self._instances[capability] = instance
        self.ctx["kernel.services"][capability_name(capability)] = instance

    def contribute[T](self, key: ContributionKey[T], value: T) -> None:
        values = self.ctx["kernel.contributions"]
        values[key.name] = (*values.get(key.name, ()), value)
        self._contributions.setdefault(key.name, []).append(value)

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]:
        return cast("tuple[T, ...]", tuple(self.ctx["kernel.contributions"].get(key.name, ())))

    def seed(self, instances: Iterable[tuple[type, object]]) -> None:
        for capability, instance in instances:
            self.provide(capability, instance)

    def seed_contributions(self, values: Iterable[tuple[ContributionKey[Any], object]]) -> None:
        for key, value in values:
            self.contribute(key, value)

    def freeze(self) -> Assembly:
        contributions = {name: tuple(values) for name, values in self._contributions.items()}
        return Assembly(self.settings, self._instances, contributions, self.modules, self.ctx)


@dataclass(frozen=True, slots=True)
class _ModuleContext:
    """按解析结果约束单个模块的登记权，读取始终面向实际公共能力。"""

    context: ModuleContext
    module_id: str
    providers: Mapping[type, str]

    @property
    def ctx(self) -> Context:
        return self.context.ctx

    @property
    def settings(self) -> Settings:
        """配置仍来自同一份只读装配输入。"""
        return self.context.settings

    @property
    def modules(self) -> tuple[ModuleSpec, ...]:
        """静态声明在准备和构造之前已就绪，不需要等待其他模块产生贡献。"""
        return self.context.modules

    def is_provider(self, capability: type) -> bool:
        """优先级裁决决定登记权，不依赖构造器到达的先后顺序。"""
        return self.providers.get(capability) == self.module_id

    def get[T](self, capability: type[T]) -> T:
        """只返回已登记的有效提供者。"""
        return self.context.get(capability)

    def get_optional[T](self, capability: type[T]) -> T | None:
        """未就绪的公共能力保持缺省，不暴露其他模块的候选实例。"""
        return self.context.get_optional(capability)

    def contains(self, capability: type) -> bool:
        """查询公共能力是否已经就绪。"""
        return self.context.contains(capability)

    def provide[T](self, capability: type[T], instance: T) -> None:
        """未选中的提供者不能抢占公共登记，未声明的可选辅助能力仍可登记。"""
        if capability in self.providers and not self.is_provider(capability):
            return
        self.context.provide(capability, instance)

    def contribute[T](self, key: ContributionKey[T], value: T) -> None:
        """贡献不因某项能力被替换而丢失。"""
        self.context.contribute(key, value)

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]:
        """所有模块共用按装配顺序形成的贡献集合。"""
        return self.context.contributions(key)
