"""实例组合根：提供类型化实例注册与读取，并冻结 ``AuroraConfig`` 为最终组装产物。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from aurora.config import AuroraConfig


@dataclass(frozen=True, slots=True)
class InstanceKey[T]:
    """标识一个由组合模块导出的项目实例。"""

    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("实例键名称不能为空")


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

    def finish(self) -> AuroraAssembly:
        return AuroraAssembly(self.config, self._instances)


type CompositionRegistrar = Callable[[CompositionContext], None]
type InstanceBinding = tuple[InstanceKey[object], object]


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """一个组合模块的声明式规格：提供什么、依赖什么、如何构造。"""

    key: InstanceKey[object]
    requires: tuple[InstanceKey[object], ...]
    register: CompositionRegistrar


@dataclass(frozen=True, slots=True)
class PackageSpec:
    """一个 src 包的组合代表：自持键、按名声明依赖、构造器。

    代表模块只导出自身包的键；兄弟包的实例一律按键名声明并到构造期由
    CompositionContext 提供，因此各代表模块之间不需要运行时相互 import。
    """

    key: InstanceKey[object]
    provides: tuple[InstanceKey[object], ...]
    requires: tuple[str, ...]
    register: CompositionRegistrar

    def __post_init__(self) -> None:
        provided_names = {item.name for item in self.provides}
        if self.key.name not in provided_names:
            raise ValueError(f"代表主键 {self.key.name} 必须包含在 provides 中")
        for name in self.requires:
            if not name.strip():
                raise ValueError("依赖键名不能为空")


def build_module_specs(packages: Iterable[PackageSpec]) -> tuple[ModuleSpec, ...]:
    """由包级代表规格合成可拓扑装配的模块规格。

    requires 以键名声明；这里校验每个依赖键名有且只有一个提供者，并把键名解析为
    提供包的代表主键，作为模块规格之间的依赖边。
    """
    listed = tuple(packages)
    owners: dict[str, PackageSpec] = {}
    for package in listed:
        for key in package.provides:
            if key.name in owners:
                raise ValueError(f"实例键被多个代表模块声明提供：{key.name}")
            owners[key.name] = package

    resolved: list[ModuleSpec] = []
    for package in listed:
        deps: list[InstanceKey[object]] = []
        for name in package.requires:
            owner = owners.get(name)
            if owner is None:
                raise ValueError(f"{package.key.name} 依赖的实例键没有提供者：{name}")
            deps.append(owner.key)
        resolved.append(ModuleSpec(key=package.key, requires=tuple(deps), register=package.register))
    return tuple(resolved)


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


def compose(
    config: AuroraConfig,
    specs: Iterable[ModuleSpec],
    instances: Iterable[InstanceBinding] = (),
) -> AuroraAssembly:
    """拓扑排序后构造所有项目实例。"""
    sorted_specs = _topo_sort(tuple(specs))
    context = CompositionContext(config)
    for key, instance in instances:
        context.provide(key, instance)
    for spec in sorted_specs:
        _logger.debug("执行组件注册 module={}", spec.key.name)
        spec.register(context)
    assembly = context.finish()
    _logger.info("项目组件装配完成 instance_count={}", len(assembly.names))
    return assembly
