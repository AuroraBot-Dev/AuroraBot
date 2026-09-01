"""运行全部组件注册器，并取得完整运行时所需实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composition import compose_project
from aurora.composition.agents import AGENTS, AGENTS_OPS, EXTERNAL_TOOLS
from aurora.composition.ai import AI_OPS, MODEL
from aurora.composition.cadence import CADENCE, CADENCE_OPS
from aurora.composition.console import CONSOLE_OPS, TERMINAL_CONSOLE
from aurora.composition.engine import ENGINE_RUNNER
from aurora.composition.mcp import MCP_OPS, MCP_RUNTIME
from aurora.composition.memory import MEMORY, MEMORY_OPS
from aurora.composition.prompt import PROMPT_OPS
from aurora.composition.tools import TOOLS_OPS
from aurora.composition.world import WORLD_JOURNAL, WORLD_OPS
from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.runtime.core import AuroraRuntime
from aurora.views import ContractsOps

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
    if model is not None:
        instances.append((MODEL, model))
    external_tools = (*tuple(tools), *(mcp.tools if mcp is not None else ()))
    if external_tools:
        instances.append((EXTERNAL_TOOLS, external_tools))
    assembly = compose_project(config, instances)
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
        assembly.get(AGENTS_OPS),
        assembly.get(TOOLS_OPS),
        assembly.get(PROMPT_OPS),
        assembly.get(AI_OPS),
        assembly.get(WORLD_OPS),
        assembly.get(CONSOLE_OPS),
        assembly.get(CADENCE_OPS),
        assembly.get(MEMORY_OPS),
        assembly.get(MCP_OPS),
        ContractsOps(),
        output=output,
    )
