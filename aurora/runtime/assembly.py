"""项目装配入口：把内建与外部模块交给组合内核，并创建进程门面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import TOOL_CONTRIBUTIONS, McpRuntime, Model, Tool, WorldJournal
from src.kernel import (
    BuiltinSource,
    DirectorySource,
    EntryPointSource,
    compose,
    compose_managed,
)
from src.runtime import AuroraRuntime, create_runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.config import AuroraConfig
    from src.kernel import ContributionBinding, InstanceBinding, ManagedAssembly


def _discover_specs(config: AuroraConfig):
    directory = config.project_root / "extensions" / "plugins"
    return (
        *BuiltinSource().discover(),
        *DirectorySource(directory).discover(),
        *EntryPointSource().discover(),
    )


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
    """同步组合全部实例后，从单一 Assembly 构造进程门面。"""
    bindings = list(instances)
    if world is not None:
        bindings.append((WorldJournal, world))
    if mcp is not None:
        bindings.append((McpRuntime, mcp))
    if model is not None:
        bindings.append((Model, model))
    contributed = [*contributions, *((TOOL_CONTRIBUTIONS, tool) for tool in tools)]
    assembly = compose(config, _discover_specs(config), bindings, contributed)
    return create_runtime(assembly, output=output)


async def assemble_runtime_managed(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    output: Callable[[str], None] = print,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> tuple[AuroraRuntime, ManagedAssembly]:
    """执行全部模块 prepare/construct，并返回运行门面与统一生命周期。"""
    bindings = list(instances)
    if model is not None:
        bindings.append((Model, model))
    contributed = [*contributions, *((TOOL_CONTRIBUTIONS, tool) for tool in tools)]
    lifecycle = await compose_managed(config, _discover_specs(config), bindings, contributed)
    try:
        return create_runtime(lifecycle.assembly, output=output), lifecycle
    except BaseException:
        await lifecycle.close()
        raise
