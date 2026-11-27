"""可选 MCP 产品装配；连接和目录先于默认 bot，世界来源复用同一客户端。"""

from functools import partial
from pathlib import Path

from aurora_core import Id
from aurora_core.ctx import Context
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import LifecycleComponent
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService
from aurora_world.configuration import configured_sources_component

ASSEMBLY = Id("org.aurora.bot:assemblies/mcp")


def assemble(
    *, registry: DefinitionRegistry, ctx: Context, hooks: HookConnections, storage: StorageService, workspace_root: Path
) -> tuple[LifecycleComponent, ...]:
    """同步连接声明；新增工具不写回 TOML，已显式选择的工具保留原实例身份。"""
    from aurora_mcp.clients import MCPClients
    from aurora_mcp.tools import MCPTools

    from .assembly import DefaultAssembly
    from .assembly_config import ToolSelection

    clients = MCPClients(ctx, hooks, workspace_root=workspace_root)
    tools = MCPTools(registry, ctx, hooks, clients)

    def additions(existing: tuple[ToolSelection, ...]) -> list[ToolSelection]:
        selected = {item["tool"] for item in existing}
        return [
            {"tool": str(identity), "instance_id": identity.local_path, "config": {}}
            for identity in tools.tool_ids
            if str(identity) not in selected
        ]

    sources = configured_sources_component
    if any(entry.id == Id("org.aurora.mcp:sources/resources") for entry in registry.entries()):
        from aurora_mcp.world import mcp_world_component

        sources = partial(mcp_world_component, clients=clients)
    bot = DefaultAssembly(
        registry=registry,
        ctx=ctx,
        hooks=hooks,
        storage=storage,
        additional_tools=additions,
        world_component_factory=sources,
    )
    return (clients.component(), tools.component(), *bot.components(depends_on=(tools.instance_id,)))


def create_host(root: Path, *, workspace_root: Path, plugins=()):
    """产品入口显式构造 MCP 与 Bot 组件，交由通用宿主管理。"""
    from aurora_host import Host, read_assembly
    from aurora_host.configuration import select_assembly

    plan = read_assembly(select_assembly(root))
    host = Host.create(plan, plugins, root, workspace_root=workspace_root)
    try:
        host.mount(assemble(**host.services))
    except BaseException:
        host.close()
        raise
    return host
