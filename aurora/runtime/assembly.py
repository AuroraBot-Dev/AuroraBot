"""运行全部组件注册器，并取得完整运行时所需实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composition import compose_project
from aurora.composition.agents import AGENTS
from aurora.composition.cadence import CADENCE
from aurora.composition.console import TERMINAL_CONSOLE
from aurora.composition.engine import ENGINE_RUNNER
from aurora.composition.mcp import MCP_RUNTIME
from aurora.composition.memory import MEMORY
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.runtime.core import AuroraRuntime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.composer import InstanceBinding
    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool, WorldJournal
    from src.mcp import McpRuntime


def assemble_runtime(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    world: WorldJournal | None = None,
    mcp: McpRuntime | None = None,
    output: Callable[[str], None] = print,
) -> AuroraRuntime:
    """运行全部组件注册器，并取得完整运行时所需实例。"""
    instances: list[InstanceBinding] = []
    if world is not None:
        instances.append((WORLD_JOURNAL, world))
    if mcp is not None:
        instances.append((MCP_RUNTIME, mcp))
    external_tools = (*tuple(tools), *(mcp.tools if mcp is not None else ()))
    assembly = compose_project(config, model, external_tools, instances)
    return AuroraRuntime(
        assembly.get(ENGINE_RUNNER),
        config.get(RUNTIME_CONFIG),
        assembly.get(AGENTS),
        config,
        assembly.get(TERMINAL_CONSOLE),
        assembly.get(WORLD_JOURNAL),
        assembly.get(CADENCE),
        assembly.get(MEMORY),
        assembly.get(MCP_RUNTIME),
        output=output,
    )
