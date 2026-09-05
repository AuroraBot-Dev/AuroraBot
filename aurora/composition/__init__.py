"""项目组件目录；各 src 包以同名模块为代表声明 provides/requires/construct，由注册表合成并拓扑装配。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import PackageSpec, build_module_specs, compose
from aurora.composition import (
    agents,
    ai,
    cadence,
    console,
    engine,
    mcp,
    memory,
    prompt,
    tools,
    world,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.composer import AuroraAssembly, InstanceBinding
    from aurora.config import AuroraConfig

PACKAGE_SPECS: tuple[PackageSpec, ...] = (
    agents.PACKAGE_SPEC,
    ai.PACKAGE_SPEC,
    cadence.PACKAGE_SPEC,
    console.PACKAGE_SPEC,
    engine.PACKAGE_SPEC,
    mcp.PACKAGE_SPEC,
    memory.PACKAGE_SPEC,
    prompt.PACKAGE_SPEC,
    tools.PACKAGE_SPEC,
    world.PACKAGE_SPEC,
)

COMPOSITION_SPECS = build_module_specs(PACKAGE_SPECS)


def compose_project(config: AuroraConfig, instances: Iterable[InstanceBinding] = ()) -> AuroraAssembly:
    return compose(config, COMPOSITION_SPECS, instances)
