"""实例组合根：提供类型化实例注册与读取，并冻结 ``AuroraConfig`` 为最终组装产物。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping

    from aurora.config import AuroraConfig


@dataclass(frozen=True, slots=True)
class InstanceKey[T]:
    """标识一个由组合模块导出的项目实例。"""

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("实例键名称不能为空")


@dataclass(frozen=True, slots=True)
class ContributionKey[T]:
    """标识允许多个模块追加同类型值的稳定组合贡献点。"""

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("贡献键名称不能为空")


@dataclass(frozen=True, slots=True)
class AuroraAssembly:
    """组合完成后的只读产物：``AuroraConfig`` 与全部已构造实例。

    config 在构造阶段即被各代表模块的 construct 读取；装入 assembly 是为了让 runtime
    拿到单一对象后自行按键拆取所需实例与配置。
    """

    config: AuroraConfig
    _instances: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_instances", MappingProxyType(dict(self._instances)))

    def get[T](self, key: InstanceKey[T]) -> T:
        try:
            instance = self._instances[key.name]
        except KeyError as error:
            raise KeyError(f"实例尚未注册：{key.name}") from error
        return cast("T", instance)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._instances)


@dataclass(slots=True)
class CompositionContext:
    """向各代表模块提供配置与已构造实例。"""

    config: AuroraConfig
    _instances: dict[str, object] = field(default_factory=dict)
    _names: set[str] = field(default_factory=set)
    _contributions: dict[str, list[object]] = field(default_factory=dict)

    def contains[T](self, key: InstanceKey[T]) -> bool:
        """返回一个分阶段预构造实例是否已经进入组合上下文。"""
        return key.name in self._names

    def contains_name(self, name: str) -> bool:
        """按键名返回分阶段预构造实例是否已经进入组合上下文。"""
        return name in self._names

    def provide[T](self, key: InstanceKey[T], instance: T) -> None:
        if key.name in self._names:
            raise ValueError(f"实例重复注册：{key.name}")
        self._names.add(key.name)
        self._instances[key.name] = instance

    def require[T](self, key: InstanceKey[T]) -> T:
        return cast("T", self.require_name(key.name))

    def require_name(self, name: str) -> object:
        """按键名读取已构造实例；代表模块用它拉取兄弟包的实例而不引入其模块。"""
        try:
            return self._instances[name]
        except KeyError as error:
            raise KeyError(f"组合依赖尚未注册：{name}") from error

    def contribute[T](self, key: ContributionKey[T], value: T) -> None:
        """向稳定贡献点追加一个值；聚合方在自身构造时读取完整冻结序列。"""
        self._contributions.setdefault(key.name, []).append(value)

    def contributions[T](self, key: ContributionKey[T]) -> tuple[T, ...]:
        """按模块拓扑顺序返回一个贡献点的全部当前值。"""
        return cast("tuple[T, ...]", tuple(self._contributions.get(key.name, ())))

    def finish(self) -> AuroraAssembly:
        return AuroraAssembly(self.config, self._instances)


type AsyncCleanup = Callable[[], Awaitable[None]]
type CompositionRegistrar = Callable[[CompositionContext], None]
type CompositionPrepare = Callable[[CompositionContext], Awaitable[AsyncCleanup | None]]
type CompositionHook = Callable[[CompositionContext], Awaitable[None]]
type CompositionRunner = Callable[[CompositionContext, asyncio.Event], Coroutine[Any, Any, None]]
type InstanceBinding = tuple[InstanceKey[object], object]
type ContributionBinding = tuple[ContributionKey[Any], object]


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """一个组合模块的声明式规格：提供什么、依赖什么、如何构造。"""

    key: InstanceKey[object]
    requires: tuple[InstanceKey[object], ...]
    register: CompositionRegistrar
    activation_after: tuple[InstanceKey[object], ...] = ()
    prepare: CompositionPrepare | None = None
    activate: CompositionHook | None = None
    run: CompositionRunner | None = None
    close: CompositionHook | None = None


@dataclass(frozen=True, slots=True)
class PackageSpec:
    """一个 src 包的组合代表：自持键、依赖、贡献与生命周期。

    代表模块只导出自身包的键；兄弟包的实例一律按键名声明并到构造期由
    CompositionContext 提供，因此各代表模块之间不需要运行时相互 import。
    """

    key: InstanceKey[object]
    provides: tuple[InstanceKey[object], ...]
    requires: tuple[str, ...]
    register: CompositionRegistrar
    contributes: tuple[ContributionKey[Any], ...] = ()
    consumes: tuple[ContributionKey[Any], ...] = ()
    activation_after: tuple[str, ...] = ()
    prepare: CompositionPrepare | None = None
    activate: CompositionHook | None = None
    run: CompositionRunner | None = None
    close: CompositionHook | None = None

    def __post_init__(self) -> None:
        provided_names = {item.name for item in self.provides}
        if self.key.name not in provided_names:
            raise ValueError(f"代表主键 {self.key.name} 必须包含在 provides 中")
        for name in self.requires:
            if not name.strip():
                raise ValueError("依赖键名不能为空")
        for name in self.activation_after:
            if not name.strip():
                raise ValueError("生命周期依赖键名不能为空")
        contribution_names = [key.name for key in (*self.contributes, *self.consumes)]
        if len(contribution_names) != len(set(contribution_names)):
            raise ValueError(f"代表模块重复声明贡献点：{self.key.name}")


def build_module_specs(packages: Iterable[PackageSpec]) -> tuple[ModuleSpec, ...]:
    """由包级代表规格合成可拓扑装配的模块规格。

    requires 以键名声明；这里校验每个依赖键名有且只有一个提供者，并把键名解析为
    提供包的代表主键。贡献消费方还自动依赖全部已发现贡献者。
    """
    listed = tuple(packages)
    owners: dict[str, PackageSpec] = {}
    contributors: dict[str, list[PackageSpec]] = {}
    for package in listed:
        for key in package.provides:
            if key.name in owners:
                raise ValueError(f"实例键被多个代表模块声明提供：{key.name}")
            owners[key.name] = package
        for key in package.contributes:
            contributors.setdefault(key.name, []).append(package)

    resolved: list[ModuleSpec] = []
    for package in listed:
        deps = _dependency_keys(package, owners, contributors)
        resolved.append(
            ModuleSpec(
                key=package.key,
                requires=tuple(deps),
                register=package.register,
                activation_after=tuple(_activation_keys(package, owners)),
                prepare=package.prepare,
                activate=package.activate,
                run=package.run,
                close=package.close,
            )
        )
    return tuple(resolved)


def _dependency_keys(
    package: PackageSpec,
    owners: Mapping[str, PackageSpec],
    contributors: Mapping[str, list[PackageSpec]],
) -> list[InstanceKey[object]]:
    """解析实例依赖并追加本包消费贡献点的全部提供者主键。"""
    deps: list[InstanceKey[object]] = []

    def add_dependency(owner: PackageSpec) -> None:
        if owner is not package and owner.key.name not in {item.name for item in deps}:
            deps.append(owner.key)

    for name in package.requires:
        owner = owners.get(name)
        if owner is None:
            raise ValueError(f"{package.key.name} 依赖的实例键没有提供者：{name}")
        add_dependency(owner)
    for key in package.consumes:
        for contributor in contributors.get(key.name, ()):
            add_dependency(contributor)
    return deps


def _activation_keys(
    package: PackageSpec,
    owners: Mapping[str, PackageSpec],
) -> list[InstanceKey[object]]:
    """把 activation_after 键名解析为对应提供者的代表主键。"""
    activation_after: list[InstanceKey[object]] = []
    for name in package.activation_after:
        owner = owners.get(name)
        if owner is None:
            raise ValueError(f"{package.key.name} 生命周期依赖的实例键没有提供者：{name}")
        if owner is not package and owner.key.name not in {item.name for item in activation_after}:
            activation_after.append(owner.key)
    return activation_after


def _validate_dependencies(specs: tuple[ModuleSpec, ...]) -> None:
    """校验所有 requires 都有对应的 spec 提供。"""
    provided_names = {s.key.name for s in specs}
    for spec in specs:
        for dep in spec.requires:
            if dep.name not in provided_names:
                raise ValueError(f"{spec.key.name} 声明依赖 {dep.name}，但没有组合模块提供它")


def _topo_sort(specs: tuple[ModuleSpec, ...]) -> list[ModuleSpec]:
    """Kahn 算法拓扑排序；检测循环依赖。"""
    _validate_dependencies(specs)

    by_key: dict[str, ModuleSpec] = {s.key.name: s for s in specs}
    in_degree: dict[str, int] = {s.key.name: 0 for s in specs}
    dependents: dict[str, list[str]] = {s.key.name: [] for s in specs}
    for spec in specs:
        for dep in spec.requires:
            if dep.name in in_degree:
                in_degree[spec.key.name] += 1
                dependents[dep.name].append(spec.key.name)

    queue = [name for name, deg in in_degree.items() if deg == 0]
    result: list[ModuleSpec] = []
    while queue:
        name = queue.pop(0)
        result.append(by_key[name])
        for dependent_name in dependents[name]:
            in_degree[dependent_name] -= 1
            if in_degree[dependent_name] == 0:
                queue.append(dependent_name)

    if len(result) != len(specs):
        cycle = {s.key.name for s in specs} - {s.key.name for s in result}
        raise ValueError(f"组合模块存在循环依赖：{', '.join(sorted(cycle))}")

    return result


def _activation_order(specs: tuple[ModuleSpec, ...]) -> tuple[ModuleSpec, ...]:
    staged = tuple(
        replace(
            spec,
            requires=tuple(dict.fromkeys((*spec.requires, *spec.activation_after))),
        )
        for spec in specs
    )
    return tuple(_topo_sort(staged))


def _composition_context(
    config: AuroraConfig,
    instances: Iterable[InstanceBinding],
    contributions: Iterable[ContributionBinding],
) -> CompositionContext:
    context = CompositionContext(config)
    for key, instance in instances:
        context.provide(key, instance)
    for key, value in contributions:
        context.contribute(key, value)
    return context


@dataclass(slots=True)
class ManagedAssembly:
    """持有一次已组合 Assembly 及其通用模块生命周期。"""

    assembly: AuroraAssembly
    _context: CompositionContext
    _specs: tuple[ModuleSpec, ...]
    _cleanups: tuple[AsyncCleanup, ...]
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _activated: bool = False
    _closed: bool = False

    async def activate(self, stop: asyncio.Event) -> None:
        """按生命周期依赖激活模块，并启动所有后台 run hook。"""
        if self._closed or self._activated:
            raise RuntimeError("模块生命周期只能激活一次")
        self._activated = True
        try:
            ordered = _activation_order(self._specs)
            for spec in ordered:
                if spec.activate is not None:
                    await spec.activate(self._context)
            self._tasks.extend(
                asyncio.create_task(spec.run(self._context, stop), name=f"aurora:{spec.key.name}")
                for spec in ordered
                if spec.run is not None
            )
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """取消后台任务，并逆序关闭模块与 prepare 资源。"""
        if self._closed:
            return
        self._closed = True
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        failures: list[Exception] = []
        for spec in reversed(self._specs):
            if spec.close is None:
                continue
            try:
                await spec.close(self._context)
            except Exception as error:  # noqa: BLE001 - 关闭必须继续释放剩余模块
                failures.append(error)
        for cleanup in reversed(self._cleanups):
            try:
                await cleanup()
            except Exception as error:  # noqa: BLE001 - 关闭必须继续释放剩余资源
                failures.append(error)
        if failures:
            raise failures[0]


def compose(
    config: AuroraConfig,
    specs: Iterable[ModuleSpec],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> AuroraAssembly:
    """拓扑排序后构造所有项目实例。"""
    sorted_specs = _topo_sort(tuple(specs))
    context = _composition_context(config, instances, contributions)
    for spec in sorted_specs:
        _logger.debug("执行组件注册 module={}", spec.key.name)
        spec.register(context)
    assembly = context.finish()
    _logger.info("项目组件装配完成 instance_count={}", len(assembly.names))
    return assembly


async def compose_managed(
    config: AuroraConfig,
    specs: Iterable[ModuleSpec],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> ManagedAssembly:
    """按依赖执行异步 prepare 与同步构造，并返回统一生命周期。"""
    sorted_specs = tuple(_topo_sort(tuple(specs)))
    context = _composition_context(config, instances, contributions)
    cleanups: list[AsyncCleanup] = []
    constructed: list[ModuleSpec] = []
    try:
        for spec in sorted_specs:
            _logger.debug("准备组件 module={}", spec.key.name)
            if spec.prepare is not None and (cleanup := await spec.prepare(context)) is not None:
                cleanups.append(cleanup)
            spec.register(context)
            constructed.append(spec)
    except BaseException:
        for spec in reversed(constructed):
            if spec.close is not None:
                with suppress(Exception):
                    await spec.close(context)
        for cleanup in reversed(cleanups):
            with suppress(Exception):
                await cleanup()
        raise
    assembly = context.finish()
    _logger.info("项目组件装配完成 instance_count={}", len(assembly.names))
    return ManagedAssembly(assembly, context, sorted_specs, tuple(cleanups))
