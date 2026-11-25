"""按配置选择 MCP 工具并原子登记到 agent；执行机制由独立模块提供。"""

import asyncio

from aurora_agent.tools import TOOLS, ToolInstance, ToolSpec
from aurora_control import ExecutionPlug, StateBinding, component_entries
from aurora_core import Id, entry_from, hook_handler
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import PREPARE, LifecycleComponent
from aurora_core.registry import DefinitionRegistry, RegistryEntry
from aurora_core.storage import StorageService

from aurora_adapter.model import JsonValue

from .catalog import discover_tools, select_tools
from .clients import MCPClients
from .errors import MCPClientError
from .tool_execution import MCPTool

COMPONENT = Id("org.aurora.adapter:components/mcp/tool")


class _Factory:
    def __init__(self, bridge: "MCPTools", connection_id: str, remote_name: str, timeout: float) -> None:
        self.bridge, self.connection_id, self.remote_name = bridge, connection_id, remote_name
        self.timeout = timeout

    async def __call__(
        self,
        *,
        ctx: Context,
        storage: StorageService,
        instance_id: str,
        input_state: StateBinding,
        output_state: StateBinding,
        config: dict[str, JsonValue],
    ) -> ToolInstance:
        if ctx is not self.bridge.ctx or not self.bridge.prepared:
            raise ValueError("MCP 工具工厂只用于已完成发现的同一宿主")
        if config:
            raise ValueError("MCP 工具实例不接受额外配置；连接与远程名称由 MCP 声明选择")
        tool = MCPTool(
            self.bridge.clients, self.connection_id, self.remote_name, self.timeout, ctx, input_state, output_state
        )
        return ToolInstance(
            ExecutionPlug(
                COMPONENT, tool.execute, {"input": input_state, "output": output_state}, instance_id=instance_id
            ),
            tool.close,
        )


class MCPTools:
    """prepare 完整发现并原子登记工具；同一总表只装配一次，目录变化须重建宿主。

    本地名称由显式别名或 v2 身份摘要生成，完整目录与冲突检查通过后才登记。
    tools/list_changed 不修改运行中的工具定义。组件必须先于工具消费者准备。
    """

    def __init__(
        self,
        registry: DefinitionRegistry,
        ctx: Context,
        hooks: HookConnections,
        clients: MCPClients,
        *,
        instance_id: str = "aurora_adapter/mcp/tools",
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("MCP 工具桥实例身份不能为空")
        self.registry, self.ctx, self.hooks, self.clients = registry, ctx, hooks, clients
        self.instance_id = instance_id
        self.prepared = False
        self._connected = False
        self._tool_ids: tuple[Id, ...] = ()

    def component(self, *, depends_on: tuple[str, ...] = ()) -> LifecycleComponent:
        """声明客户端依赖，不访问网络；bot components 的 depends_on 应引用本组件。"""
        if self._connected or self.prepared:
            raise RuntimeError("MCP 工具桥已连接或完成准备")
        entry = entry_from(self.prepare, provider="aurora_adapter.mcp.tools")
        self.hooks.connect(
            PREPARE, entry.id, slot_instance=self.instance_id, handler_instance=self.instance_id, target=self.prepare
        )
        self._connected = True
        return LifecycleComponent(
            self.instance_id, depends_on=tuple(dict.fromkeys((self.clients.instance_id, *depends_on)))
        )

    @property
    def tool_ids(self) -> tuple[Id, ...]:
        """当前宿主已完成发现的工具身份；产品装配据此增加显式实例选择。"""
        if not self.prepared:
            raise RuntimeError("MCP 工具尚未完成发现")
        return self._tool_ids

    @hook_handler("org.aurora.adapter:handlers/mcp/tools/prepare", slot=PREPARE)
    async def prepare(self) -> None:
        if self.prepared:
            raise RuntimeError("MCP 工具已登记；工具集合变化须重建宿主")
        servers = self.clients.server_configurations()
        names = {
            entry.target.definition["name"]
            for entry in self.registry.view(register_to=TOOLS)
            if isinstance(entry.target, ToolSpec)
        }
        entries = []
        for connection_id, server in sorted(servers.items()):
            selection = server["tools"]
            if not selection["include"] and not selection["exclude"]:
                continue
            async with asyncio.timeout(server["timeout"]["catalog"]), self.clients.connection(connection_id) as client:
                catalog = await discover_tools(client, selection)
            for name, remote in select_tools(connection_id, selection, catalog):
                if name in names:
                    raise MCPClientError("tool_name_conflict")
                names.add(name)
                spec = ToolSpec(
                    COMPONENT,
                    {"name": name, "description": remote.description or "", "parameters": remote.input_schema},
                    factory=_Factory(self, connection_id, remote.name, server["timeout"]["execution"]),
                )
                entries.append(
                    RegistryEntry(
                        Id(f"org.aurora.adapter:tools/mcp/{name}"),
                        "tool",
                        spec,
                        "aurora_adapter.mcp.tools",
                        register_to=TOOLS,
                    )
                )
        self.registry.register_many(entries)
        self._tool_ids = tuple(entry.id for entry in entries)
        self.prepared = True


def plugin() -> Plugin:
    """声明工具执行组件和发现入口；启用插件本身不创建连接或发现工具。"""
    return Plugin(
        "aurora_adapter.mcp.tools",
        (
            *component_entries(COMPONENT, MCPTool, MCPTool.execute, provider="aurora_adapter.mcp.tools"),
            entry_from(MCPTools.prepare, provider="aurora_adapter.mcp.tools"),
        ),
        requires=("aurora_adapter.mcp", "aurora_agent.tools"),
    )
