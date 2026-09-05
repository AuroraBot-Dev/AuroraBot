"""项目组件目录；需要构造实例的下层包在此声明规格并由拓扑排序驱动装配。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import ModuleSpec, compose
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

COMPOSITION_SPECS: tuple[ModuleSpec, ...] = (
    world.MODULE_SPEC,
    mcp.MODULE_SPEC,
    memory.MODULE_SPEC,
    cadence.MODULE_SPEC,
    agents.MODULE_SPEC,
    ai.MODULE_SPEC,
    prompt.MODULE_SPEC,
    console.MODULE_SPEC,
    tools.MODULE_SPEC,
    engine.MODULE_SPEC,
)


def compose_project(
    config: AuroraConfig,
    instances: Iterable[InstanceBinding] = (),
) -> AuroraAssembly:
    return compose(config, COMPOSITION_SPECS, instances)
