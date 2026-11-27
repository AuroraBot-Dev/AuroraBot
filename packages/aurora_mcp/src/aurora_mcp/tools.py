"""按配置选择 MCP 工具并原子登记到 tools；执行机制由独立模块提供。"""

import asyncio

from aurora_control import ExecutionPlug, StateBinding
from aurora_core import Id, plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.json_data import JsonValue
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService
from aurora_tools.execution import TOOLS, ToolInstance, ToolSpec

from .catalog import discover_tools, select_tools
from .clients import MCPClients
from .errors import MCPClientError
from .plugins.tools._meta import COMPONENT, EXECUTE, TOOL_DEFINITIONS, tools_plugin
from .plugins.tools._meta import PREPARE as CATALOG_PREPARE
from .tool_execution import MCPTool


class _Factory:
    def __init__(self, connection_id: str, remote_name: str, timeout: float) -> None:
        self.connection_id, self.remote_name = connection_id, remote_name
        self.timeout = timeout

    async def __call__(
        self,
        *,
        ctx: Context,
        storage: StorageService,
        instance_id: str,
        input_state: StateBinding,
        output_state: StateBinding,
        owner,
        resources,
        config: dict[str, JsonValue],
    ) -> ToolInstance:
        if config:
            raise ValueError("MCP 工具实例不接受额外配置；连接与远程名称由 MCP 声明选择")
        tool = MCPTool(
            resources["clients"], self.connection_id, self.remote_name, self.timeout, ctx, input_state, output_state
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
        clients: MCPClients | None = None,
        *,
        instance_id: str = "aurora_mcp/tools",
    ) -> None:
        if not instance_id or not instance_id.strip():
            raise ValueError("MCP 工具桥实例身份不能为空")
        self.registry, self.ctx, self.clients = registry, ctx, clients
        self.instance_id = instance_id
        self.prepared = False
        self._tool_ids: tuple[Id, ...] = ()

    def definitions(self):
        return [self.registry.get(identity).target.definition for identity in self.tool_ids]

    def bind(self, *, clients):
        self.clients = clients

    @property
    def tool_ids(self) -> tuple[Id, ...]:
        """当前宿主已完成发现的工具身份；产品装配据此增加显式实例选择。"""
        if not self.prepared:
            raise RuntimeError("MCP 工具尚未完成发现")
        return self._tool_ids

    @plug(CATALOG_PREPARE)
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
                    factory=_Factory(connection_id, remote.name, server["timeout"]["execution"]),
                )
                entries.append(TOOL_DEFINITIONS.bind(name, spec))
        self.registry.register_many(entries)
        self._tool_ids = tuple(entry.id for entry in entries)
        self.prepared = True


def plugin() -> Plugin:
    return tools_plugin(
        targets={COMPONENT: MCPTool, EXECUTE: MCPTool.execute},
        components={
            "catalog": ComponentFactory(
                MCPTools,
                lambda instance: InstanceExport(
                    plugs={CATALOG_PREPARE: instance.prepare}, resources={"catalog": instance}
                ),
                plugs=(MCPTools.prepare,),
                bind=lambda instance, resources: instance.bind(**resources),
            ),
        },
    )
