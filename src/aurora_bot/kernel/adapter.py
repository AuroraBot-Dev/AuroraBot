"""把 Bot 的契约、贡献和生命周期声明连接到通用宿主。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora_bot.kernel.context import ModuleContext
from aurora_bot.kernel.declaration import ModuleSpec
from aurora_kernel.declaration import Manifest, Namespace
from aurora_kernel.declaration import ModuleSpec as HostModule
from aurora_kernel.phase import PhaseKind

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from aurora_bot.kernel.context import _MutableContext
    from aurora_kernel import Context


type ModuleDeclaration = ModuleSpec | HostModule | Namespace


def providers(specs: Iterable[ModuleDeclaration], selected: Mapping[str, str]) -> dict[str, str]:
    return {
        capability: selected[capability]
        for spec in specs
        if isinstance(spec, ModuleSpec)
        for capability in spec.provides
        if capability in selected
    }


def declarations(
    specs: Iterable[ModuleDeclaration],
    context: _MutableContext | None = None,
    selected: dict[str, str] | None = None,
) -> tuple[HostModule, ...]:
    """资源和世界域仍留在 Bot；宿主只获得名称与普通回调。"""
    listed = tuple(specs)
    result = []
    for item in listed:
        spec = item.spec if isinstance(item, Namespace) else item
        if isinstance(spec, HostModule):
            result.append(spec)
        elif isinstance(spec, ModuleSpec):
            result.append(_declaration(spec, context, selected))
        else:
            raise TypeError("模块必须是 namespace 或 ModuleSpec 声明")
    return tuple(result)


def _declaration(spec: ModuleSpec, context: _MutableContext | None, selected: dict[str, str] | None) -> HostModule:
    hooks = dict(spec.hooks)
    if context is not None and selected is not None:
        hooks = {
            phase: _callback(spec, callback, context, selected, build=phase.kind is PhaseKind.BUILD)
            for phase, callback in spec.hooks.items()
        }
    return HostModule(
        spec.module_id,
        provides=spec.provides,
        requires=spec.requires,
        contributes=tuple(key.name for key in spec.contributes),
        consumes=tuple(key.name for key in spec.consumes),
        declares=tuple(key.name for key in spec.declares),
        priority=spec.priority,
        optional=spec.optional,
        order=spec.order,
        hooks=hooks,
        points=spec.points,
        handlers=spec.handlers,
        manifest=Manifest(spec.manifest.version, spec.manifest.kernel_api),
    )


def _callback(
    spec: ModuleSpec, callback: Callable, context: _MutableContext, selected: dict[str, str], *, build: bool
) -> Callable:
    def call(_ctx: Context, *args: Any) -> Any:
        bound = ModuleContext(context, spec.module_id, selected)
        result = callback(bound, *args)
        if build:
            for capability in spec.provides:
                if bound.is_provider(capability) and not bound.contains(capability):
                    raise ValueError(f"{spec.module_id} 声明提供 {capability}，但构造期没有登记它")
        return result

    return call
