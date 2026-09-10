"""项目组件目录；自动发现功能包与进程门面的唯一 ``PACKAGE_SPEC``。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import PackageSpec, build_module_specs, compose, compose_managed
from aurora.utils.modules import discover_modules

if TYPE_CHECKING:
    from collections.abc import Iterable
    from types import ModuleType

    from aurora.composer import AuroraAssembly, ContributionBinding, InstanceBinding, ManagedAssembly
    from aurora.config import AuroraConfig


def _package_spec(module: ModuleType) -> PackageSpec:
    spec = getattr(module, "PACKAGE_SPEC", None)
    if not isinstance(spec, PackageSpec):
        raise TypeError(f"组合模块必须导出唯一 PACKAGE_SPEC：{module.__name__}")
    return spec


PACKAGE_SPECS = tuple(
    _package_spec(module) for module in discover_modules(__name__, tuple(str(path) for path in __path__))
)

COMPOSITION_SPECS = build_module_specs(PACKAGE_SPECS)


def compose_project(
    config: AuroraConfig,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> AuroraAssembly:
    return compose(config, COMPOSITION_SPECS, instances, contributions)


async def compose_project_managed(
    config: AuroraConfig,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> ManagedAssembly:
    return await compose_managed(config, COMPOSITION_SPECS, instances, contributions)
