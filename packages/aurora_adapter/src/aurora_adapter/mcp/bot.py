"""可选 MCP 产品装配；连接和目录先于默认 bot，世界来源复用同一客户端。"""

from functools import partial
from pathlib import Path

from aurora_bot.assembly import DefaultAssembly
from aurora_bot.assembly_config import ToolSelection
from aurora_core import Id
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import LifecycleComponent
from aurora_core.registry import DefinitionRegistry, RegistryEntry
from aurora_core.storage import StorageService
from aurora_world.configuration import configured_sources_component

from .clients import MCPClients
from .tools import MCPTools
from .world import WORLD_SOURCE, mcp_world_component

ASSEMBLY = Id("org.aurora.adapter:assemblies/mcp/default_bot")


def assemble(
    *, registry: DefinitionRegistry, ctx: Context, hooks: HookConnections, storage: StorageService, workspace_root: Path
) -> tuple[LifecycleComponent, ...]:
    """同步连接声明；新增工具不写回 TOML，已显式选择的工具保留原实例身份。"""
    clients = MCPClients(ctx, hooks, workspace_root=workspace_root)
    tools = MCPTools(registry, ctx, hooks, clients)

    def additions(existing: tuple[ToolSelection, ...]) -> list[ToolSelection]:
        selected = {item["tool"] for item in existing}
        return [
            {"tool": str(identity), "instance_id": identity.local_path, "config": {}}
            for identity in tools.tool_ids
            if str(identity) not in selected
        ]

    sources = (
        partial(mcp_world_component, clients=clients)
        if any(entry.id == WORLD_SOURCE for entry in registry.entries())
        else configured_sources_component
    )
    bot = DefaultAssembly(
        registry=registry,
        ctx=ctx,
        hooks=hooks,
        storage=storage,
        additional_tools=additions,
        world_component_factory=sources,
    )
    return (clients.component(), tools.component(), *bot.components(depends_on=(tools.instance_id,)))


def plugin() -> Plugin:
    """安装 extra 与启用插件分开；不隐式启用依赖或创建运行资源。"""
    return Plugin(
        "aurora_adapter.mcp.bot",
        (
            RegistryEntry(
                ASSEMBLY,
                "assembly",
                assemble,
                "aurora_adapter.mcp.bot",
                register_to=Id("org.aurora.core:registries/resources"),
            ),
        ),
        requires=("aurora_adapter.mcp.tools", "aurora_bot.assembly"),
    )
