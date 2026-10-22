from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, Any

from aurora_kernel import Context

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from aurora_bot.contracts import ContributionKey, Settings
    from aurora_bot.kernel.declaration import ModuleSpec

SERVICES = "bot.services"
CONTRIBUTIONS = "bot.contributions"


class _Access:
    __slots__ = ()
    ctx: Context

    def get(self, name: str) -> Any:
        try:
            return self.ctx[SERVICES][name]
        except KeyError as error:
            raise LookupError(f"模块尚未提供：{name}") from error

    def get_optional(self, name: str) -> Any:
        return self.ctx[SERVICES].get(name)

    def contains(self, name: str) -> bool:
        return name in self.ctx[SERVICES]

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]:
        return tuple(self.ctx[CONTRIBUTIONS].get(key.name, ()))


@dataclass(frozen=True, slots=True)
class Assembly(_Access):
    settings: Settings
    _instances: InitVar[Mapping[str, object]]
    _contributions: InitVar[Mapping[str, tuple[object, ...]]]
    modules: tuple[ModuleSpec, ...] = ()
    ctx: Context = field(default_factory=Context, compare=False)

    def __post_init__(self, _instances: Mapping[str, object], _contributions: Mapping[str, tuple[object, ...]]) -> None:
        object.__setattr__(self, "modules", tuple(self.modules))
        if SERVICES not in self.ctx:
            self.ctx.ensure(SERVICES).update(_instances)
        if CONTRIBUTIONS not in self.ctx:
            self.ctx.ensure(CONTRIBUTIONS).update(_contributions)

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(self.ctx[SERVICES])


@dataclass(slots=True)
class _MutableContext(_Access):
    settings: Settings
    modules: tuple[ModuleSpec, ...] = ()
    ctx: Context = field(default_factory=Context, compare=False)

    def __post_init__(self) -> None:
        self.ctx.ensure(SERVICES)
        self.ctx.ensure(CONTRIBUTIONS)
        self.ctx.ensure("aurora.bot")["settings"] = self.settings

    def provide(self, name: str, instance: object) -> None:
        with self.ctx.transaction() as staged:
            if name in staged[SERVICES]:
                raise ValueError(f"模块重复提供：{name}")
            staged[SERVICES][name] = instance

    def contribute[T](self, key: ContributionKey[T], value: T) -> None:
        with self.ctx.transaction() as staged:
            values = staged[CONTRIBUTIONS]
            values[key.name] = (*values.get(key.name, ()), value)

    def seed(self, instances: Iterable[tuple[str, object]]) -> None:
        for name, instance in instances:
            self.provide(name, instance)

    def seed_contributions(self, values: Iterable[tuple[ContributionKey[Any], object]]) -> None:
        for key, value in values:
            self.contribute(key, value)

    def freeze(self) -> Assembly:
        return Assembly(self.settings, {}, {}, self.modules, self.ctx)


@dataclass(frozen=True, slots=True)
class ModuleContext(_Access):
    context: _MutableContext
    module_id: str
    providers: Mapping[str, str]
    ctx: Context = field(init=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ctx", self.context.ctx)

    @property
    def settings(self) -> Settings:
        return self.context.settings

    @property
    def modules(self) -> tuple[ModuleSpec, ...]:
        return self.context.modules

    def is_provider(self, name: str) -> bool:
        return self.providers.get(name) == self.module_id

    def provide(self, name: str, instance: object) -> None:
        if name not in self.providers or self.is_provider(name):
            self.context.provide(name, instance)

    def contribute[T](self, key: ContributionKey[T], value: T) -> None:
        self.context.contribute(key, value)


Capabilities = Assembly
