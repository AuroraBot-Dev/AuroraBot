"""项目装配入口：发现全部模块声明并交给组合内核，返回进程门面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import LOOP_OPERATIONS, TOOL_CONTRIBUTIONS, WORLD_PORTS, ScopeCatalog, Tool
from src.contracts.pkgs.ai import Model
from src.contracts.pkgs.mcp import McpRuntime
from src.contracts.pkgs.world import WorldJournal
from src.kernel import (
    BuiltinSource,
    Capabilities,
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


def declared_scopes(specs: Iterable[ModuleSpec]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """汇总全部模块声明所拥有与所观察的域，去重后按名称排序。"""
    owns = {scope for spec in specs for scope in spec.owns_scopes}
    observes = {scope for spec in specs for scope in spec.observes_scopes}
    return tuple(sorted(owns)), tuple(sorted(observes))


def validate_declared_scopes(settings: Settings, specs: Iterable[ModuleSpec]) -> None:
    """模块声明拥有或观察的域必须被域注册表覆盖；未注册即启动前失败。"""
    owns, observes = declared_scopes(specs)
    undeclared = settings.resolve(ScopeCatalog).undeclared((*owns, *observes))
    if undeclared:
        raise ValueError(f"模块声明了未注册的域：{', '.join(undeclared)}")


def validate_loop_operations(capabilities: Capabilities) -> None:
    """ReAct 四操作必须齐备，并且 Observe 与 Effect 必须落在同一个世界上。

    四操作由 ``provides`` 契约表达，所以内核本来就能替换它们；这里补的是
    **替换之后仍然是一个完整循环**：缺一个操作就不是循环，而观察与效果落在
    两个世界上时，Bot 会经历一个自己写不进去的世界。
    """
    missing = [
        operation.name for operation in LOOP_OPERATIONS if capabilities.get_optional(operation.capability) is None
    ]
    if missing:
        raise ValueError(f"ReAct 循环缺少操作实现：{', '.join(missing)}")
    worlds = [capabilities.get(port) for port in WORLD_PORTS]
    if any(world is not worlds[0] for world in worlds[1:]):
        names = "、".join(port.__name__ for port in WORLD_PORTS)
        raise ValueError(f"Observe 与 Effect 必须是同一个世界：{names} 必须由同一个对象提供")


def _sources(settings: Settings) -> tuple[DiscoverySource, ...]:
    plugin_directory = settings.project_root.joinpath(*_PLUGIN_DIRECTORY)
    return (BuiltinSource(), DirectorySource(plugin_directory), EntryPointSource())


def _discover(settings: Settings) -> tuple[ModuleSpec, ...]:
    specs = tuple(spec for source in _sources(settings) for spec in source.discover())
    validate_declared_scopes(settings, specs)
    return specs


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
    validate_loop_operations(assembly)
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
