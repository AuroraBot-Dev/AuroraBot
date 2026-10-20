"""模块依赖解析：冲突裁决、缺失依赖、可选跳过、环检测与阶段计划编译。"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurorabot.kernel.api import KERNEL_API_VERSION
from aurorabot.kernel.phase import ACTIVATE, BUILTIN_PHASES, CONSTRUCT, CONSTRUCTION_KINDS, PREPARE, Phase

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from aurorabot.kernel.declaration import ModuleSpec


@dataclass(frozen=True, slots=True)
class PhaseStep:
    """一个阶段及其参与模块的有序列表。"""

    phase: Phase
    modules: tuple[ModuleSpec, ...]


@dataclass(frozen=True, slots=True)
class Resolution:
    """一次解析结果：构造顺序、激活顺序与完整阶段计划。"""

    phases: tuple[PhaseStep, ...]
    providers: Mapping[type, str]
    modules: tuple[ModuleSpec, ...]

    def __post_init__(self) -> None:
        """登记权属于冻结的解析结果，运行阶段不能重新选择提供者。"""
        object.__setattr__(self, "providers", MappingProxyType(dict(self.providers)))
        object.__setattr__(self, "modules", tuple(self.modules))

    @property
    def construction(self) -> tuple[ModuleSpec, ...]:
        """构造顺序直接来自阶段计划，不另存第二份可漂移的结果。"""
        return self.step(CONSTRUCT)

    @property
    def activation(self) -> tuple[ModuleSpec, ...]:
        """激活顺序与执行生命周期时读取的是同一份阶段计划。"""
        return self.step(ACTIVATE)

    def step(self, phase: Phase) -> tuple[ModuleSpec, ...]:
        for entry in self.phases:
            if entry.phase == phase:
                return entry.modules
        return ()


def resolve(specs: Iterable[ModuleSpec]) -> Resolution:
    listed = tuple(specs)
    _validate_module_api(listed)
    _validate_identities(listed)
    available = _drop_unsatisfied_optional(listed)
    providers = _providers(available)
    active = tuple(
        spec
        for spec in available
        if not spec.provides
        or spec.contributes
        or any(providers[item].module_id == spec.module_id for item in spec.provides)
    )
    _validate_requires(active, providers)
    contributors = _contributors(active)
    _validate_declarations(active, available)
    _validate_orderings(active)

    construction = _topological(
        sorted(active, key=lambda spec: spec.module_id), _construction_dependencies(active, providers, contributors)
    )
    phases = _collect_phases(active)
    _validate_phase_groups(phases)
    steps = tuple(PhaseStep(phase, _phase_modules(phase, providers, construction)) for phase in phases)
    return Resolution(
        phases=steps,
        providers={capability: spec.module_id for capability, spec in providers.items()},
        modules=tuple(available),
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
    providers: Mapping[type, ModuleSpec],
    construction: tuple[ModuleSpec, ...],
) -> tuple[ModuleSpec, ...]:
    if phase == CONSTRUCT:
        return construction
    if phase == PREPARE:
        return tuple(spec for spec in construction if spec.participates(PREPARE))
    base = tuple(reversed(construction)) if phase.shutdown else construction
    participants = tuple(spec for spec in base if spec.participates(phase))
    dependencies = {spec.module_id: _ordering_dependencies(spec, phase, providers) for spec in participants}
    return _topological(participants, dependencies)


def _validate_module_api(specs: tuple[ModuleSpec, ...]) -> None:
    """在筛选、准备与构造之前检查全部声明，跳过策略不能绕过兼容约束。"""
    for spec in specs:
        if not spec.manifest.accepts(KERNEL_API_VERSION):
            raise ValueError(
                f"模组 {spec.module_id}（{spec.manifest.version}）与内核 API {KERNEL_API_VERSION} 不兼容，"
                f"要求：{spec.manifest.kernel_api}"
            )


def _validate_identities(specs: tuple[ModuleSpec, ...]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.module_id in seen:
            raise ValueError(f"模块名称重复：{spec.module_id}")
        seen.add(spec.module_id)


def _drop_unsatisfied_optional(specs: tuple[ModuleSpec, ...]) -> list[ModuleSpec]:
    remaining = list(specs)
    while True:
        available = {capability for spec in remaining for capability in spec.provides}
        skipped = {spec.module_id for spec in remaining if _is_unsatisfied(spec, available)}
        if not skipped:
            return remaining
        remaining = [spec for spec in remaining if spec.module_id not in skipped]


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
        ordered = sorted(candidates, key=lambda spec: (-spec.priority, spec.module_id))
        if ordered[0].priority == ordered[1].priority:
            names = ", ".join(spec.module_id for spec in ordered)
            raise ValueError(f"能力 {capability.__name__} 被多个同优先级模块提供：{names}")
        providers[capability] = ordered[0]
    return providers


def _validate_requires(specs: Iterable[ModuleSpec], providers: Mapping[type, ModuleSpec]) -> None:
    for spec in specs:
        for requirement in spec.requires:
            if requirement not in providers:
                raise ValueError(f"{spec.module_id} 依赖的能力没有提供者：{requirement.__name__}")


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
            declared.setdefault(key.name, []).append(spec.module_id)
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
                raise ValueError(f"{spec.module_id} 的 {ordering.phase.name} 约束引用了更晚阶段 {target.name}")


def _construction_dependencies(
    specs: Iterable[ModuleSpec],
    providers: Mapping[type, ModuleSpec],
    contributors: Mapping[str, list[ModuleSpec]],
) -> dict[str, set[str]]:
    """能力与贡献依赖编译为同一张图，由排序统一处理自依赖。"""
    return {
        spec.module_id: {providers[requirement].module_id for requirement in spec.requires}
        | {contributor.module_id for key in spec.consumes for contributor in contributors.get(key.name, ())}
        for spec in specs
    }


def _ordering_dependencies(spec: ModuleSpec, phase: Phase, providers: Mapping[type, ModuleSpec]) -> set[str]:
    result: set[str] = set()
    for ordering in spec.order:
        if ordering.phase != phase:
            continue
        target = ordering.after_phase or phase
        if target != phase:
            continue
        for capability in ordering.after:
            if capability in providers:
                result.add(providers[capability].module_id)
    return result


def _topological(
    specs: Iterable[ModuleSpec],
    dependencies: Mapping[str, set[str]],
) -> tuple[ModuleSpec, ...]:
    """按依赖排序；同时就绪的模块保持输入顺序，不依赖集合遍历顺序。"""
    ordered = tuple(specs)
    positions = {spec.module_id: index for index, spec in enumerate(ordered)}
    names = set(positions)
    resolved = {name: dependencies[name] & (names - {name}) for name in positions}
    in_degree = {name: len(deps) for name, deps in resolved.items()}
    dependents: dict[str, set[str]] = {spec.module_id: set() for spec in ordered}
    for name, deps in resolved.items():
        for dependency in deps:
            dependents[dependency].add(name)

    queue = [positions[name] for name, degree in in_degree.items() if degree == 0]
    heapq.heapify(queue)
    result: list[ModuleSpec] = []
    while queue:
        spec = ordered[heapq.heappop(queue)]
        result.append(spec)
        for dependent in dependents[spec.module_id]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                heapq.heappush(queue, positions[dependent])

    if len(result) != len(ordered):
        cycle = sorted(names - {spec.module_id for spec in result})
        raise ValueError(f"模块存在循环依赖：{' → '.join(cycle)}")
    return tuple(result)
