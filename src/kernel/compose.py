"""组合入口：解析模块依赖并构造只读 Assembly 或统一生命周期。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from src.kernel.context import _ModuleContext, _MutableContext
from src.kernel.failures import ModuleCleanup, collect_failure
from src.kernel.lifecycle import ManagedAssembly
from src.kernel.phase import CLOSE, CONSTRUCTION_KINDS, PhaseKind
from src.kernel.resolve import resolve
from src.utils import get_logger
from src.utils.tasks import raise_with_cleanup, wait_for_completion

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from src.contracts import ContributionKey, Settings
    from src.kernel.context import Assembly
    from src.kernel.declaration import ModuleHook, ModulePrepare, ModuleRegistrar, ModuleSpec

_logger = get_logger(__name__)

type InstanceBinding = tuple[type, object]
type ContributionBinding = tuple[ContributionKey[Any], object]


def _validate_provides(spec: ModuleSpec, context: _ModuleContext) -> None:
    """仅核对当前模块实际被选中的能力，其他端口由其有效提供者登记。"""
    for capability in spec.provides:
        if context.is_provider(capability) and not context.contains(capability):
            raise ValueError(f"{spec.module_id} 声明提供 {capability.__name__}，但构造期没有登记它")


def compose(
    settings: Settings,
    specs: Iterable[ModuleSpec],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> Assembly:
    """拓扑排序后同步构造所有模块（不执行异步 prepare）。"""
    resolution = resolve(specs)
    context = _MutableContext(settings, modules=resolution.modules)
    context.seed(instances)
    context.seed_contributions(contributions)
    for step in resolution.phases:
        if step.phase.kind is not PhaseKind.BUILD:
            continue
        for spec in step.modules:
            hook = spec.hook(step.phase)
            if hook is None:
                continue
            _logger.debug("执行组件注册 module={}", spec.module_id)
            bound = _ModuleContext(context, spec.module_id, resolution.providers)
            cast("ModuleRegistrar", hook)(bound)
            _validate_provides(spec, bound)
    assembly = context.freeze()
    _logger.info("项目组件装配完成 capability_count={}", len(assembly.capabilities))
    return assembly


async def compose_managed(
    settings: Settings,
    specs: Iterable[ModuleSpec],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> ManagedAssembly:
    """按阶段执行全部构造阶段（prepare/construct），并返回统一生命周期。"""
    resolution = resolve(specs)
    context = _MutableContext(settings, modules=resolution.modules)
    context.seed(instances)
    context.seed_contributions(contributions)
    cleanups: list[ModuleCleanup] = []
    constructed: list[ModuleSpec] = []
    try:
        for step in resolution.phases:
            if step.phase.kind not in CONSTRUCTION_KINDS:
                continue
            for spec in step.modules:
                hook = spec.hook(step.phase)
                if hook is None:
                    continue
                _logger.debug("构造组件 module={} phase={}", spec.module_id, step.phase.name)
                bound = _ModuleContext(context, spec.module_id, resolution.providers)
                if step.phase.kind is PhaseKind.SETUP:
                    cleanup = await cast("ModulePrepare", hook)(bound)
                    if cleanup is not None:
                        cleanups.append(ModuleCleanup(spec.module_id, step.phase.name, cleanup))
                else:
                    cast("ModuleRegistrar", hook)(bound)
                    _validate_provides(spec, bound)
                    constructed.append(spec)
    except BaseException as error:
        _logger.exception("模组装配失败，开始回滚")
        rollback = asyncio.create_task(
            _rollback(context, constructed, cleanups, resolution.providers), name="aurora:rollback"
        )
        failures, interrupted = await wait_for_completion(rollback)
        raise_with_cleanup(error, failures, interrupted)
    assembly = context.freeze()
    _logger.info("项目组件装配完成 capability_count={}", len(assembly.capabilities))
    return ManagedAssembly(assembly, context, resolution, tuple(cleanups))


async def _rollback(
    context: _MutableContext,
    constructed: list[ModuleSpec],
    cleanups: list[ModuleCleanup],
    providers: Mapping[type, str],
) -> list[Exception]:
    """回滚保留失败归属，调用者同时报告构造失败与所有释放失败。"""
    failures: list[Exception] = []
    closed: set[str] = set()
    for spec in reversed(constructed):
        if spec.module_id in closed:
            continue
        closed.add(spec.module_id)
        hook = spec.hook(CLOSE)
        if hook is not None:
            bound = _ModuleContext(context, spec.module_id, providers)
            failure = await collect_failure(spec.module_id, CLOSE.name, cast("ModuleHook", hook)(bound))
            if failure is not None:
                failures.append(failure)
    for cleanup in reversed(cleanups):
        failure = await cleanup.run()
        if failure is not None:
            failures.append(failure)
    return failures
