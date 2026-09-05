"""从单一 AuroraAssembly（含 AuroraConfig）构造进程门面。

本模块是唯一读取 ``aurora.composition`` 键与配置规格的运行时装配点：
进程门面本身只依赖注入的协作者，不随新增组合模块增长。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composition import compose_project, compose_project_managed
from aurora.composition.agents import AGENTS
from aurora.composition.ai import MODEL
from aurora.composition.cadence import CADENCE
from aurora.composition.console import TERMINAL_CONSOLE
from aurora.composition.engine import ENGINE_RUNNER
from aurora.composition.mcp import MCP_CLIENT_FACTORY, MCP_RUNTIME
from aurora.composition.memory import MEMORY
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.contributions import TOOL_CONTRIBUTIONS
from aurora.runtime.core import AuroraRuntime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.composer import AuroraAssembly, ContributionBinding, InstanceBinding, ManagedAssembly
    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool, WorldJournal
    from src.mcp import McpClientFactory, McpRuntime


def assemble_runtime(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    world: WorldJournal | None = None,
    mcp: McpRuntime | None = None,
    output: Callable[[str], None] = print,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> AuroraRuntime:
    """组合全部实例后，从单一 assembly 构造进程门面。"""
    bindings = list(instances)
    if world is not None:
        bindings.append((WORLD_JOURNAL, world))
    if mcp is not None:
        bindings.append((MCP_RUNTIME, mcp))
    if model is not None:
        bindings.append((MODEL, model))
    contributed = [*contributions, *((TOOL_CONTRIBUTIONS, tool) for tool in tools)]
    assembly = compose_project(config, bindings, contributed)
    return runtime_from_assembly(assembly, output=output)


async def assemble_runtime_managed(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    output: Callable[[str], None] = print,
    mcp_factory: McpClientFactory | None = None,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> tuple[AuroraRuntime, ManagedAssembly]:
    """执行全部模块 prepare/construct，并返回运行门面与统一生命周期。"""
    bindings = list(instances)
    if model is not None:
        bindings.append((MODEL, model))
    if mcp_factory is not None:
        bindings.append((MCP_CLIENT_FACTORY, mcp_factory))
    contributed = [*contributions, *((TOOL_CONTRIBUTIONS, tool) for tool in tools)]
    lifecycle = await compose_project_managed(config, bindings, contributed)
    try:
        return runtime_from_assembly(lifecycle.assembly, output=output), lifecycle
    except BaseException:
        await lifecycle.close()
        raise


def runtime_from_assembly(
    assembly: AuroraAssembly,
    *,
    output: Callable[[str], None] = print,
) -> AuroraRuntime:
    """把已组合完成的 assembly（实例 + AuroraConfig）构造为进程门面。"""
    runtime = AuroraRuntime(
        assembly,
        runner=assembly.get(ENGINE_RUNNER),
        agents=assembly.get(AGENTS),
        root=assembly.config.get(RUNTIME_CONFIG),
        console=assembly.get(TERMINAL_CONSOLE),
        world=assembly.get(WORLD_JOURNAL),
        cadence=assembly.get(CADENCE),
        memory=assembly.get(MEMORY),
        mcp=assembly.get(MCP_RUNTIME),
        output=output,
    )
    runtime.cadence.bind_launcher(runtime)
    return runtime
