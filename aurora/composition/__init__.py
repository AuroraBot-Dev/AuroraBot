"""项目组件目录；需要构造实例的下层包在此显式注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import compose
from aurora.composition import (
    agents,
    ai,
    console,
    engine,
    prompt,
    tools,
    world,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.composer import AuroraAssembly
    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool

COMPOSITION_REGISTRARS = (
    agents.register,
    ai.register,
    prompt.register,
    console.register,
    world.register,
    tools.register,
    engine.register,
)


def compose_project(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
) -> AuroraAssembly:
    return compose(config, model, COMPOSITION_REGISTRARS, tools)


__all__ = ["COMPOSITION_REGISTRARS", "compose_project"]
