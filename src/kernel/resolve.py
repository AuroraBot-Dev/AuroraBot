"""模块依赖解析：冲突裁决、缺失依赖、可选跳过、环检测与拓扑排序。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from src.kernel.declaration import ModuleSpec


@dataclass(frozen=True, slots=True)
class Resolution:
    """一次解析结果：构造顺序与激活顺序。"""

    construction: tuple[ModuleSpec, ...]
    activation: tuple[ModuleSpec, ...]


def resolve(specs: Iterable[ModuleSpec]) -> Resolution:
    listed = tuple(specs)
    _validate_names(listed)
    active = _drop_unsatisfied_optional(listed)
    providers = _providers(active)
    _validate_requires(active, providers)
    contributors = _contributors(active)
    construction = _topological(active, providers, contributors, include_activation=False)
    activation = _topological(active, providers, contributors, include_activation=True)
    return Resolution(construction=tuple(construction), activation=tuple(activation))


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


def _dependencies(
    spec: ModuleSpec,
    providers: Mapping[type, ModuleSpec],
    contributors: Mapping[str, list[ModuleSpec]],
    *,
    include_activation: bool,
) -> set[str]:
    dependencies: set[str] = set()
    requirements = list(spec.requires)
    if include_activation:
        requirements.extend(spec.activation_after)
    for requirement in requirements:
        _add(dependencies, providers.get(requirement), spec)
    for key in spec.consumes:
        for contributor in contributors.get(key.name, ()):
            _add(dependencies, contributor, spec)
    return dependencies


def _add(dependencies: set[str], module: ModuleSpec | None, spec: ModuleSpec) -> None:
    if module is not None and module.name != spec.name:
        dependencies.add(module.name)


def _topological(
    specs: Iterable[ModuleSpec],
    providers: Mapping[type, ModuleSpec],
    contributors: Mapping[str, list[ModuleSpec]],
    *,
    include_activation: bool,
) -> list[ModuleSpec]:
    ordered = sorted(specs, key=lambda spec: spec.name)
    by_name = {spec.name: spec for spec in ordered}
    dependencies = {
        spec.name: _dependencies(spec, providers, contributors, include_activation=include_activation)
        for spec in ordered
    }
    in_degree = {name: len(deps) for name, deps in dependencies.items()}
    dependents: dict[str, set[str]] = {spec.name: set() for spec in ordered}
    for name, deps in dependencies.items():
        for dependency in deps:
            dependents[dependency].add(name)

    queue = sorted(name for name, degree in in_degree.items() if degree == 0)
    result: list[ModuleSpec] = []
    while queue:
        name = queue.pop(0)
        result.append(by_name[name])
        for dependent in sorted(dependents[name]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
        queue.sort()

    if len(result) != len(ordered):
        cycle = sorted({spec.name for spec in ordered} - {spec.name for spec in result})
        raise ValueError(f"模块存在循环依赖：{' → '.join(cycle)}")
    return result
