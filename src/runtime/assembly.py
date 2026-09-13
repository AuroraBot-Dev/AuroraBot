"""项目装配入口：发现全部模块声明并交给组合内核，返回进程门面。"""

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
from src.runtime.factory import RuntimeFactory

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from src.contracts import Settings
    from src.kernel import (
        Assembly,
        ContributionBinding,
        DiscoverySource,
        InstanceBinding,
        ManagedAssembly,
        ModuleSpec,
    )
    from src.runtime.core import AuroraRuntime

_PLUGIN_DIRECTORY = ("extensions", "plugins")


def _sources(settings: Settings) -> tuple[DiscoverySource, ...]:
    plugin_directory = settings.project_root.joinpath(*_PLUGIN_DIRECTORY)
    return (BuiltinSource(), DirectorySource(plugin_directory), EntryPointSource())


def _discover(settings: Settings) -> tuple[ModuleSpec, ...]:
    return tuple(spec for source in _sources(settings) for spec in source.discover())


def _seed(
    model: Model | None,
    tools: Iterable[Tool],
    instances: Iterable[InstanceBinding],
    contributions: Iterable[ContributionBinding],
) -> tuple[list[InstanceBinding], list[ContributionBinding]]:
    bindings = list(instances)
    if model is not None:
        bindings.append((Model, model))
    contributed = [*contributions, *((TOOL_CONTRIBUTIONS, tool) for tool in tools)]
    return bindings, contributed


def _create(assembly: Assembly, output: Callable[[str], None]) -> AuroraRuntime:
    factory = assembly.get(RuntimeFactory)
    return factory(assembly, output=output)


def assemble_runtime(
    settings: Settings,
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
    bindings, contributed = _seed(model, tools, instances, contributions)
    if world is not None:
        bindings.append((WorldJournal, world))
    if mcp is not None:
        bindings.append((McpRuntime, mcp))
    assembly = compose(settings, _discover(settings), bindings, contributed)
    return _create(assembly, output)


async def compose_runtime(
    settings: Settings,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    output: Callable[[str], None] = print,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> tuple[AuroraRuntime, ManagedAssembly]:
    """执行全部模块 prepare/construct，并返回运行门面与统一生命周期。"""
    bindings, contributed = _seed(model, tools, instances, contributions)
    lifecycle = await compose_managed(settings, _discover(settings), bindings, contributed)
    try:
        return _create(lifecycle.assembly, output), lifecycle
    except BaseException:
        await lifecycle.close()
        raise
