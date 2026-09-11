"""从唯一 Assembly 构造 ops 所需的实例化窄端口。

ops 作为 backend 自持全部监测业务：世界、目录、节律与平台事实都从 assembly 的实例或
配置直接派生；aurora 不再装配这些端口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from aurora.configuration.endpoints import ENDPOINTS_CONFIG
from aurora.configuration.engine import ENGINE_CONFIG
from aurora.configuration.platforms import PLATFORMS_CONFIG
from aurora.configuration.providers import PROVIDERS_CONFIG
from ops.config import ConfigAccess, ConfigSourceRef
from ops.contracts import OpsPorts
from ops.views import agent_dict, commit_dict, contracts_status, mcp_app_dict, tool_dict, utils_status
from src.contracts import (
    AgentCatalog,
    AgentTreeRunner,
    Cadence,
    McpRuntime,
    MemoryReader,
    PromptAssembler,
    ToolRegistry,
    WorldJournal,
)

if TYPE_CHECKING:
    from typing import Protocol

    from aurora.config import AuroraConfig
    from src.kernel import Assembly

    class _ConsolePlatform(Protocol):
        id: str
        enabled: bool


_CONSOLE_PLATFORM_ID = "builtin.console"


class WorldPort:
    """WorldJournal 实例的窄监测端口。"""

    def __init__(self, world: WorldJournal) -> None:
        self._world = world

    async def world_stream(self, *, after: int = 0, limit: int = 64) -> dict[str, Any]:
        if after < 0:
            raise ValueError("after 必须是不小于 0 的整数")
        await self._world.initialize()
        page = await self._world.stream(after, limit)
        return {
            "after": page.after,
            "end": page.end,
            "has_more": page.has_more,
            "commits": [commit_dict(commit) for commit in page.commits],
        }

    async def world_commit(self, commit_id: str) -> dict[str, Any] | None:
        await self._world.initialize()
        commit = await self._world.commit(commit_id)
        return commit_dict(commit) if commit is not None else None


class EnginePort:
    """已冻结 Engine 配置的窄监测端口。"""

    def __init__(self, configuration: object) -> None:
        self._configuration = configuration

    def engine_status(self) -> dict[str, Any]:
        configuration = cast("Any", self._configuration)
        return {
            "max_depth": configuration.max_depth,
            "max_nodes": configuration.max_nodes,
            "max_steps": configuration.max_steps,
        }


class AgentsPort:
    """AgentCatalog 实例的窄监测端口。"""

    def __init__(self, agents: AgentCatalog) -> None:
        self._agents = agents

    def agent_catalog(self) -> dict[str, Any]:
        return {"agents": [agent_dict(definition) for definition in self._agents.definitions]}

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        try:
            definition = self._agents.get(agent_id)
        except ValueError:
            return None
        return agent_dict(definition)


class ToolsPort:
    """ToolRegistry 实例的窄监测端口。"""

    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools

    def tool_catalog(self) -> dict[str, Any]:
        return {"tools": [tool_dict(definition) for definition in self._tools.definitions]}

    def tool_detail(self, tool_id: str) -> dict[str, Any] | None:
        definition = next((item for item in self._tools.definitions if item.name == tool_id), None)
        return tool_dict(definition) if definition is not None else None


class PromptPort:
    """PromptAssembler 目录的窄监测端口。"""

    def __init__(self, assembler: PromptAssembler) -> None:
        self._system = assembler.catalog.system
        self._agent_prompts = assembler.catalog.agent_prompts

    def prompt_catalog(self) -> dict[str, Any]:
        return {
            "system": list(self._system),
            "agent_prompts": dict(self._agent_prompts),
        }

    def prompt_detail(self, prompt_id: str) -> dict[str, Any] | None:
        if prompt_id == "system":
            return {"prompt_id": "system", "fragments": list(self._system)}
        content = self._agent_prompts.get(prompt_id)
        return {"prompt_id": prompt_id, "content": content} if content is not None else None


class AiPort:
    """providers/endpoints 配置的窄监测端口。"""

    def __init__(self, providers: tuple[Any, ...], endpoints: tuple[Any, ...]) -> None:
        self._providers = providers
        self._endpoints = endpoints

    def model_catalog(self) -> dict[str, Any]:
        return {
            "providers": [
                {
                    "provider_id": provider.name,
                    "adapter": provider.adapter,
                    "secret_env": provider.secret_env,
                    "base_url": provider.base_url,
                }
                for provider in self._providers
            ],
            "endpoints": [
                {"endpoint_id": endpoint.name, "provider": endpoint.provider, "model": endpoint.model}
                for endpoint in self._endpoints
            ],
        }

    def model_detail(self, endpoint_id: str) -> dict[str, Any] | None:
        endpoint = next((item for item in self._endpoints if item.name == endpoint_id), None)
        if endpoint is None:
            return None
        provider = next((item for item in self._providers if item.name == endpoint.provider), None)
        return {
            "endpoint_id": endpoint_id,
            "provider": endpoint.provider,
            "model": endpoint.model,
            "adapter": provider.adapter if provider else None,
            "secret_env": provider.secret_env if provider else None,
            "base_url": provider.base_url if provider else None,
        }


class ConsolePort:
    """console 平台的窄监测端口。"""

    def __init__(self, platform: object) -> None:
        self._console = cast("_ConsolePlatform", platform)

    def console_status(self) -> dict[str, Any]:
        return {
            "enabled": self._console.enabled,
            "input_to_worldline": True,
            "output_to_worldline": False,
            "scope": "aurora:console",
        }


class CadencePort:
    """Cadence 实例的窄监测端口。"""

    def __init__(self, cadence: Cadence) -> None:
        self._cadence = cadence

    def cadence_status(self) -> dict[str, Any]:
        return self._cadence.status()


class MemoryPort:
    """Memory 实例的窄监测端口。"""

    def __init__(self, memory: MemoryReader, world: WorldJournal) -> None:
        self._memory = memory
        self._world = world

    async def memory_snapshot(self) -> dict[str, Any]:
        await self._world.initialize()
        snapshot = await self._memory.recall()
        return {
            "window_start": snapshot.window_start.isoformat(),
            "scopes": [
                {
                    "scope": scope.scope,
                    "head": scope.head,
                    "commits": [commit_dict(commit) for commit in scope.commits],
                }
                for scope in snapshot.scopes
            ],
        }


class McpPort:
    """McpRuntime 实例的窄监测端口。"""

    def __init__(self, runtime: McpRuntime) -> None:
        self._runtime = runtime

    def mcp_status(self) -> dict[str, Any]:
        snapshot = self._runtime.snapshot()
        return {
            "platform_enabled": snapshot.platform_enabled,
            "restart_required": snapshot.restart_required,
            "tool_ids": list(snapshot.tool_ids),
            "apps": [mcp_app_dict(app) for app in snapshot.apps],
        }

    def mcp_app(self, package: str) -> dict[str, Any] | None:
        snapshot = self._runtime.app(package)
        return mcp_app_dict(snapshot) if snapshot is not None else None


class UtilsPort:
    """共享工具能力的无状态窄端口。"""

    def utils_status(self) -> dict[str, Any]:
        return utils_status()


class ContractsPort:
    """公共契约的无状态窄端口。"""

    def contracts_status(self) -> dict[str, Any]:
        return contracts_status()


def build_ops_ports(assembly: Assembly) -> OpsPorts:
    """把 assembly 的能力与配置组装成 handlers 可见的只读 OpsPorts。"""
    config = cast("AuroraConfig", assembly.settings)
    config_access = ConfigAccess(
        config.project_root,
        tuple(ConfigSourceRef(source.name, source.relative_path) for source in config.sources),
    )
    world = assembly.get_optional(WorldJournal)
    agents = assembly.get_optional(AgentCatalog)
    tools = assembly.get_optional(ToolRegistry)
    assembler = assembly.get_optional(PromptAssembler)
    memory = assembly.get_optional(MemoryReader)
    cadence = assembly.get_optional(Cadence)
    mcp = assembly.get_optional(McpRuntime)
    engine = assembly.get_optional(AgentTreeRunner)
    platform_console = next(
        (item for item in config.get(PLATFORMS_CONFIG).platforms if item.id == _CONSOLE_PLATFORM_ID),
        None,
    )
    return OpsPorts(
        engine=EnginePort(config.get(ENGINE_CONFIG)) if engine is not None else None,
        config=config_access,
        agents=AgentsPort(agents) if agents is not None else None,
        tools=ToolsPort(tools) if tools is not None else None,
        prompt=PromptPort(assembler) if assembler is not None else None,
        ai=AiPort(config.get(PROVIDERS_CONFIG).providers, config.get(ENDPOINTS_CONFIG).endpoints),
        world=WorldPort(world) if world is not None else None,
        console=ConsolePort(platform_console) if platform_console is not None else None,
        utils=UtilsPort(),
        contracts=ContractsPort(),
        cadence=CadencePort(cadence) if cadence is not None else None,
        memory=MemoryPort(memory, world) if memory is not None and world is not None else None,
        mcp=McpPort(mcp) if mcp is not None else None,
    )
