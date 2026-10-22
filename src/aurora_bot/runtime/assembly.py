"""项目装配入口：发现全部模块声明并交给组合内核，返回进程门面。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora_bot.contracts import TOOL_CONTRIBUTIONS, ScopeCatalog, Tool
from aurora_bot.contracts.scope import merge_scope_catalog
from aurora_bot.kernel import (
    BuiltinSource,
    Capabilities,
    DirectorySource,
    EntryPointSource,
    compose,
    compose_managed,
    resolve,
)
from aurora_bot.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora_bot.contracts import Settings
    from aurora_bot.contracts.pkgs.ai import Model
    from aurora_bot.contracts.pkgs.mcp import McpRuntime
    from aurora_bot.contracts.pkgs.world import WorldJournal
    from aurora_bot.kernel import (
        Assembly,
        ContributionBinding,
        InstanceBinding,
        ManagedAssembly,
        ModuleSpec,
    )
    from aurora_bot.runtime.core import AuroraRuntime

_logger = get_logger(__name__)

_PLUGIN_DIRECTORY = ("extensions", "plugins")


def declared_scopes(specs: Iterable[ModuleSpec]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """汇总全部模块声明所拥有与所观察的域，去重后按名称排序。"""
    specs = tuple(specs)
    owns = {scope for spec in specs for scope in spec.owned_scopes}
    observes = {scope for spec in specs for scope in spec.observes_scopes}
    return tuple(sorted(owns)), tuple(sorted(observes))


def validate_declared_scopes(settings: Settings, specs: Iterable[Any]) -> None:
    """模块声明拥有或观察的域必须被域注册表覆盖；未注册即启动前失败。"""
    available = resolve(specs).modules
    owns, observes = declared_scopes(available)
    catalog = merge_scope_catalog(
        settings.resolve(ScopeCatalog), (scope for spec in available for scope in spec.scopes)
    )
    undeclared = catalog.undeclared((*owns, *observes))
    if undeclared:
        raise ValueError(f"模块声明了未注册的域：{', '.join(undeclared)}")


def validate_world(capabilities: Capabilities) -> None:
    worlds = [capabilities.get(name) for name in ("world", "world.reader", "world.writer")]
    if any(world is not worlds[0] for world in worlds[1:]):
        raise ValueError("世界读写必须使用同一个日志实例")


def _discover(settings: Settings) -> tuple[Any, ...]:
    plugin_directory = settings.project_root.joinpath(*_PLUGIN_DIRECTORY)
    sources = (
        BuiltinSource(),
        DirectorySource(plugin_directory),
        EntryPointSource(),
        EntryPointSource("aurora_module"),
    )
    specs = tuple(spec for source in sources for spec in source.discover())
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
        bindings.append(("ai", model))
    contributed = [*contributions, *((TOOL_CONTRIBUTIONS, tool) for tool in tools)]
    return bindings, contributed


def _create(assembly: Assembly, output: Callable[[str], None]) -> AuroraRuntime:
    validate_world(assembly)
    factory = assembly.get("runtime")
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
        bindings.append(("world", world))
    if mcp is not None:
        bindings.append(("mcp", mcp))
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
    except BaseException as error:
        _logger.exception("Bot 门面创建失败，开始关闭模组")
        await lifecycle.abort(error)
