"""Bot 组合适配入口；解析和生命周期均交给通用宿主。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aurora_bot.contracts import ContributionKey, Settings
from aurora_bot.kernel.adapter import declarations, providers
from aurora_bot.kernel.context import Assembly, _MutableContext
from aurora_bot.kernel.declaration import ModuleSpec
from aurora_bot.kernel.lifecycle import ManagedAssembly
from aurora_kernel import Host

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora_bot.kernel.adapter import ModuleDeclaration


type InstanceBinding = tuple[str, object]
type ContributionBinding = tuple[ContributionKey[Any], object]


def _host(
    settings: Settings,
    specs: Iterable[ModuleDeclaration],
    instances: Iterable[InstanceBinding],
    contributions: Iterable[ContributionBinding],
) -> tuple[Host, _MutableContext]:
    listed = tuple(specs)
    context = _MutableContext(settings)
    selected: dict[str, str] = {}
    host = Host(declarations(listed, context, selected), ctx=context.ctx)
    selected.update(providers(listed, host.resolution.providers))
    available = {spec.module_id for spec in host.resolution.modules}
    context.modules = tuple(spec for spec in listed if isinstance(spec, ModuleSpec) and spec.module_id in available)
    context.seed(instances)
    context.seed_contributions(contributions)
    return host, context


def compose(
    settings: Settings,
    specs: Iterable[ModuleDeclaration],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> Assembly:
    host, context = _host(settings, specs, instances, contributions)
    host.build()
    return context.freeze()


async def compose_managed(
    settings: Settings,
    specs: Iterable[ModuleDeclaration],
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> ManagedAssembly:
    host, context = _host(settings, specs, instances, contributions)
    lifecycle = await host.prepare()
    try:
        return ManagedAssembly(context.freeze(), lifecycle)
    except BaseException as error:
        logging.getLogger(__name__).exception("Bot 能力目录创建失败，开始关闭模块")
        await lifecycle.abort(error)
