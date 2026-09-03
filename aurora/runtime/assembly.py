"""从单一 AuroraAssembly（含 AuroraConfig）构造进程门面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composition import compose_project
from aurora.composition.agents import EXTERNAL_TOOLS
from aurora.composition.ai import MODEL
from aurora.composition.mcp import MCP_RUNTIME
from aurora.composition.world import WORLD_JOURNAL
from aurora.runtime.core import AuroraRuntime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.composer import AuroraAssembly, InstanceBinding
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
    """组合全部实例后，从单一 assembly 构造进程门面。"""
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
    return runtime_from_assembly(assembly, output=output)


def runtime_from_assembly(
    assembly: AuroraAssembly,
    *,
    output: Callable[[str], None] = print,
) -> AuroraRuntime:
    """把已组合完成的 assembly（实例 + AuroraConfig）构造为进程门面。"""
    return AuroraRuntime(assembly, output=output)
