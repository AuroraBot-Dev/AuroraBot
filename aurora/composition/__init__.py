"""项目组件目录；需要构造实例的下层包在此显式注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import compose
from aurora.composition import (
    agents,
    ai,
    cadence,
    console,
    engine,
    memory,
    prompt,
    tools,
    world,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.composer import AuroraAssembly
    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool

# world 是逻辑事件总线：组合时第一个实例化，后续组件只能通过同一实例键取得单例。
COMPOSITION_REGISTRARS = (
    world.register,
    memory.register,
    cadence.register,
    agents.register,
    ai.register,
    prompt.register,
    console.register,
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
