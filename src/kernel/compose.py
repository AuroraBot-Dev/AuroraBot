"""组合入口：解析模块依赖并构造只读 Assembly 或统一生命周期。"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from src.kernel.context import _MutableContext
from src.kernel.lifecycle import ManagedAssembly
from src.kernel.resolve import resolve
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.contracts import ContributionKey, Settings
    from src.kernel.context import Assembly
    from src.kernel.declaration import AsyncCleanup, ModuleSpec

_logger = get_logger(__name__)

type InstanceBinding = tuple[type, object]
type ContributionBinding = tuple[ContributionKey[object], object]


def _validate_provides(spec: ModuleSpec, context: _MutableContext) -> None:
    for capability in spec.provides:
        if not context.contains(capability):
            raise ValueError(f"{spec.name} 声明提供 {capability.__name__}，但构造期没有登记它")


def compose(
    settings: Settings,
    specs: Iterable[ModuleSpec],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> Assembly:
    """拓扑排序后同步构造所有模块（不执行异步 prepare）。"""
    resolution = resolve(specs)
    context = _MutableContext(settings)
    context.seed(instances)
    context.seed_contributions(contributions)
    for spec in resolution.construction:
        _logger.debug("执行组件注册 module={}", spec.name)
        if spec.register is not None:
            spec.register(context)
        _validate_provides(spec, context)
    assembly = context.freeze()
    _logger.info("项目组件装配完成 capability_count={}", len(assembly.capabilities))
    return assembly


async def compose_managed(
    settings: Settings,
    specs: Iterable[ModuleSpec],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> ManagedAssembly:
    """按依赖执行异步 prepare 与同步构造，并返回统一生命周期。"""
    resolution = resolve(specs)
    context = _MutableContext(settings)
    context.seed(instances)
    context.seed_contributions(contributions)
    cleanups: list[AsyncCleanup] = []
    constructed: list[ModuleSpec] = []
    try:
        for spec in resolution.construction:
            _logger.debug("准备组件 module={}", spec.name)
            if spec.prepare is not None and (cleanup := await spec.prepare(context)) is not None:
                cleanups.append(cleanup)
            if spec.register is not None:
                spec.register(context)
            _validate_provides(spec, context)
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
    assembly = context.freeze()
    _logger.info("项目组件装配完成 capability_count={}", len(assembly.capabilities))
    return ManagedAssembly(assembly, context, resolution, tuple(cleanups))
