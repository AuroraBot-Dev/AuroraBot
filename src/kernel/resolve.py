"""模块依赖解析：冲突裁决、缺失依赖、可选跳过、环检测与阶段计划编译。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.kernel.phase import ACTIVATE, BUILTIN_PHASES, CONSTRUCT, CONSTRUCTION_KINDS, PREPARE, Phase

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from src.kernel.declaration import ModuleSpec


@dataclass(frozen=True, slots=True)
class PhaseStep:
    """一个阶段及其参与模块的有序列表。"""

    phase: Phase
    modules: tuple[ModuleSpec, ...]


@dataclass(frozen=True, slots=True)
class Resolution:
    """一次解析结果：构造顺序、激活顺序与完整阶段计划。"""

    construction: tuple[ModuleSpec, ...]
    activation: tuple[ModuleSpec, ...]
    phases: tuple[PhaseStep, ...]
    providers: Mapping[type, str]

    def __post_init__(self) -> None:
        """登记权属于冻结的解析结果，运行阶段不能重新选择提供者。"""
        object.__setattr__(self, "providers", MappingProxyType(dict(self.providers)))

    def step(self, phase: Phase) -> tuple[ModuleSpec, ...]:
        for entry in self.phases:
            if entry.phase == phase:
                return entry.modules
        return ()


def resolve(specs: Iterable[ModuleSpec]) -> Resolution:
    listed = tuple(specs)
    _validate_names(listed)
    available = _drop_unsatisfied_optional(listed)
    providers = _providers(available)
    active = tuple(
        spec
        for spec in available
        if not spec.provides or spec.contributes or any(providers[item].name == spec.name for item in spec.provides)
    )
    _validate_requires(active, providers)
    contributors = _contributors(active)
    _validate_declarations(active, available)
    _validate_orderings(active)

    construction = _topological(active, _construction_dependencies(providers, contributors), _by_name)
    phases = _collect_phases(active)
    _validate_phase_groups(phases)
    steps = tuple(PhaseStep(phase, _phase_modules(phase, active, providers, construction)) for phase in phases)
    return Resolution(
        construction=construction,
        activation=_step_of(steps, ACTIVATE),
        phases=steps,
        providers={capability: spec.name for capability, spec in providers.items()},
    )


def _collect_phases(specs: Iterable[ModuleSpec]) -> tuple[Phase, ...]:
    phases = set(BUILTIN_PHASES)
    for spec in specs:
        phases.update(spec.hooks)
        for ordering in spec.order:
            phases.add(ordering.phase)
            if ordering.after_phase is not None:
                phases.add(ordering.after_phase)
    return tuple(sorted(phases, key=lambda phase: (phase.order, phase.name)))


def _validate_phase_groups(phases: Iterable[Phase]) -> None:
    construction = [phase for phase in phases if phase.kind in CONSTRUCTION_KINDS]
    startup = [phase for phase in phases if phase.kind not in CONSTRUCTION_KINDS and not phase.shutdown]
    shutdown = [phase for phase in phases if phase.shutdown]
    if construction and startup and max(phase.order for phase in construction) >= min(phase.order for phase in startup):
        raise ValueError("构造阶段必须全部早于运行阶段")
    if startup and shutdown and max(phase.order for phase in startup) >= min(phase.order for phase in shutdown):
        raise ValueError("运行阶段必须全部早于关闭阶段")


def _phase_modules(
    phase: Phase,
    specs: Iterable[ModuleSpec],
    providers: Mapping[type, ModuleSpec],
    construction: tuple[ModuleSpec, ...],
) -> tuple[ModuleSpec, ...]:
    if phase == CONSTRUCT:
        return construction
    if phase == PREPARE:
        return tuple(spec for spec in construction if spec.participates(PREPARE))
    base = tuple(reversed(construction)) if phase.shutdown else construction
    return _ordered(specs, phase, providers, base)


def _step_of(steps: Iterable[PhaseStep], phase: Phase) -> tuple[ModuleSpec, ...]:
    for step in steps:
        if step.phase == phase:
            return step.modules
    return ()


def _by_name(spec: ModuleSpec) -> tuple[int, str]:
    return (0, spec.name)


def _validate_names(specs: tuple[ModuleSpec, ...]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise ValueError(f"模块名称重复：{spec.name}")
        seen.add(spec.name)


def _drop_unsatisfied_optional(specs: tuple[ModuleSpec, ...]) -> list[ModuleSpec]:
    remaining = list(specs)
    while True:
        available = {capability for spec in remaining for capability in spec.provides}
        skipped = {spec.name for spec in remaining if _is_unsatisfied(spec, available)}
        if not skipped:
            return remaining
        remaining = [spec for spec in remaining if spec.name not in skipped]


def _is_unsatisfied(spec: ModuleSpec, available: set[type]) -> bool:
    return spec.optional and any(requirement not in available for requirement in spec.requires)


def _providers(specs: Iterable[ModuleSpec]) -> dict[type, ModuleSpec]:
    grouped: dict[type, list[ModuleSpec]] = {}
    for spec in specs:
        for capability in spec.provides:
            grouped.setdefault(capability, []).append(spec)
    providers: dict[type, ModuleSpec] = {}
    for capability, candidates in grouped.items():
        if len(candidates) == 1:
            providers[capability] = candidates[0]
            continue
        ordered = sorted(candidates, key=lambda spec: (-spec.priority, spec.name))
        if ordered[0].priority == ordered[1].priority:
            names = ", ".join(spec.name for spec in ordered)
            raise ValueError(f"能力 {capability.__name__} 被多个同优先级模块提供：{names}")
        providers[capability] = ordered[0]
    return providers


def _validate_requires(specs: Iterable[ModuleSpec], providers: Mapping[type, ModuleSpec]) -> None:
    for spec in specs:
        for requirement in spec.requires:
            if requirement not in providers:
                raise ValueError(f"{spec.name} 依赖的能力没有提供者：{requirement.__name__}")


def _contributors(specs: Iterable[ModuleSpec]) -> dict[str, list[ModuleSpec]]:
    contributors: dict[str, list[ModuleSpec]] = {}
    for spec in specs:
        for key in spec.contributes:
            contributors.setdefault(key.name, []).append(spec)
    return contributors


def _validate_declarations(specs: Iterable[ModuleSpec], owners: Iterable[ModuleSpec]) -> None:
    """能力实现可以被替换，贡献点的声明仍由原始命名空间所有者提供。"""
    referenced: set[str] = set()
    for spec in specs:
        referenced.update(key.name for key in (*spec.contributes, *spec.consumes))
    declared: dict[str, list[str]] = {}
    for spec in owners:
        for key in spec.declares:
            declared.setdefault(key.name, []).append(spec.name)
    missing = sorted(referenced - set(declared))
    if missing:
        raise ValueError(f"贡献点未被任何模块声明：{', '.join(missing)}")
    duplicated = sorted(name for name, owners in declared.items() if len(owners) > 1)
    if duplicated:
        raise ValueError(f"贡献点被多个模块声明：{', '.join(duplicated)}")


def _validate_orderings(specs: Iterable[ModuleSpec]) -> None:
    for spec in specs:
        for ordering in spec.order:
            target = ordering.after_phase or ordering.phase
            if target.order > ordering.phase.order:
                raise ValueError(f"{spec.name} 的 {ordering.phase.name} 约束引用了更晚阶段 {target.name}")


def _construction_dependencies(
    providers: Mapping[type, ModuleSpec],
    contributors: Mapping[str, list[ModuleSpec]],
) -> Callable[[ModuleSpec], set[str]]:
    def dependencies(spec: ModuleSpec) -> set[str]:
        result: set[str] = set()
        for requirement in spec.requires:
            _add(result, providers.get(requirement), spec)
        for key in spec.consumes:
            for contributor in contributors.get(key.name, ()):
                _add(result, contributor, spec)
        return result

    return dependencies


def _ordering_dependencies(spec: ModuleSpec, phase: Phase, providers: Mapping[type, ModuleSpec]) -> set[str]:
    result: set[str] = set()
    for ordering in spec.order:
        if ordering.phase != phase:
            continue
        target = ordering.after_phase or phase
        if target != phase:
            continue
        for capability in ordering.after:
            _add(result, providers.get(capability), spec)
    return result


def _add(dependencies: set[str], module: ModuleSpec | None, spec: ModuleSpec) -> None:
    if module is not None and module.name != spec.name:
        dependencies.add(module.name)


def _ordered(
    specs: Iterable[ModuleSpec],
    phase: Phase,
    providers: Mapping[type, ModuleSpec],
    base_order: Iterable[ModuleSpec],
) -> tuple[ModuleSpec, ...]:
    participants = [spec for spec in specs if spec.participates(phase)]
    if not participants:
        return ()
    index = {spec.name: position for position, spec in enumerate(base_order)}

    def key(spec: ModuleSpec) -> tuple[int, str]:
        return (index.get(spec.name, len(index)), spec.name)

    return _topological(participants, lambda spec: _ordering_dependencies(spec, phase, providers), key)


def _topological(
    specs: Iterable[ModuleSpec],
    dependencies: Callable[[ModuleSpec], set[str]],
    order_key: Callable[[ModuleSpec], tuple[int, str]],
) -> tuple[ModuleSpec, ...]:
    ordered = sorted(specs, key=order_key)
    by_name = {spec.name: spec for spec in ordered}
    names = set(by_name)
    resolved = {
        spec.name: {name for name in dependencies(spec) if name in names and name != spec.name} for spec in ordered
    }
    in_degree = {name: len(deps) for name, deps in resolved.items()}
    dependents: dict[str, set[str]] = {spec.name: set() for spec in ordered}
    for name, deps in resolved.items():
        for dependency in deps:
            dependents[dependency].add(name)

    queue = sorted(
        (name for name, degree in in_degree.items() if degree == 0),
        key=lambda name: order_key(by_name[name]),
    )
    result: list[ModuleSpec] = []
    while queue:
        name = queue.pop(0)
        result.append(by_name[name])
        for dependent in sorted(dependents[name]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
        queue.sort(key=lambda name: order_key(by_name[name]))

    if len(result) != len(ordered):
        cycle = sorted(names - {spec.name for spec in result})
        raise ValueError(f"模块存在循环依赖：{' → '.join(cycle)}")
    return tuple(result)
