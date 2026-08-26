"""组合项目实例并提供 AuroraBot 运行入口。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora import runtime_views
from aurora.composition import compose_project
from aurora.composition.agents import AGENTS
from aurora.composition.cadence import CADENCE
from aurora.composition.console import TERMINAL_CONSOLE
from aurora.composition.engine import ENGINE_RUNNER
from aurora.composition.mcp import MCP_RUNTIME, build_mcp_specs
from aurora.composition.memory import MEMORY
from aurora.composition.world import WORLD_JOURNAL, build_world
from aurora.configuration import load_config
from aurora.configuration.models import MODELS_CONFIG
from aurora.configuration.platforms import PLATFORMS_CONFIG
from aurora.configuration.prompts import PROMPTS_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG, RuntimeConfig
from aurora.configuration.storage import STORAGE_CONFIG
from aurora.panel_runtime import PanelRuntime, close_panel, run_panel
from aurora.runtime_support import (
    InstalledSignal,
    configure_project_logging,
    install_stop_handlers,
    parse_event_time,
    restore_stop_handlers,
)
from ops import ConfigAccess, ConfigSourceRef, OpsRuntime
from ops.contracts import OperationControl
from src.console import TerminalConsole, TerminalControl, TerminalResponse
from src.contracts import (
    AgentTree,
    EnvironmentEvent,
    WorldFrontier,
    WorldJournal,
)
from src.mcp import McpRuntime, prepare_mcp
from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.composer import InstanceBinding
    from aurora.config import AuroraConfig
    from src.agents import AgentCatalog
    from src.cadence import Cadence
    from src.contracts import Model, Tool, TreeLaunchRequest
    from src.engine import AgentTreeRunner
    from src.mcp import McpClientFactory
    from src.memory import Memory


@dataclass(slots=True)
class AuroraRuntime:
    """保留项目级构造边界，同时只运行 AgentTree 核心。"""

    runner: AgentTreeRunner
    root: RuntimeConfig
    agents: AgentCatalog
    config: AuroraConfig
    console: TerminalConsole
    world: WorldJournal
    cadence: Cadence
    memory: Memory
    mcp: McpRuntime
    output: Callable[[str], None] = field(default=print)
    _trees: dict[str, AgentTree] = field(default_factory=dict, init=False, repr=False)
    _stop_requester: Callable[[], None] | None = field(default=None, init=False, repr=False)
    ops: OpsRuntime = field(init=False)

    def __post_init__(self) -> None:
        self.cadence.bind_launcher(self)
        sources = tuple(ConfigSourceRef(source.name, source.relative_path) for source in self.config.sources)
        self.ops = OpsRuntime(
            self,
            ConfigAccess(self.config.project_root, sources),
            self,
            agents=self,
            tools=self,
            prompt=self,
            ai=self,
            world=self,
            console=self,
            utils=self,
            contracts=self,
            cadence=self,
            memory=self,
            mcp=self,
            config_reload=self,
        )

    def create_tree(
        self,
        message: str,
        *,
        tree_id: str | None = None,
        frontier: WorldFrontier | None = None,
    ) -> AgentTree:
        return AgentTree.create(
            tree_id or uuid4().hex,
            self.root.node_id,
            self.agents.get(self.root.agent),
            message,
            frontier,
        )

    async def run(self, message: str, *, tree_id: str | None = None) -> AgentTree:
        tree = self.create_tree(message, tree_id=tree_id)
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        _logger.info("AgentTree 已提交 tree_id=%s", tree.tree_id)
        return await self.runner.run(tree, observer=self._record_tree)

    async def start_tree(self, message: str, *, tree_id: str | None = None) -> dict[str, Any]:
        return runtime_views.tree_dict(await self.run(message, tree_id=tree_id))

    async def launch_tree(self, request: TreeLaunchRequest) -> dict[str, Any]:
        """cadence 等主动策略的统一唤起入口。"""
        definition = self.agents.get(request.agent or self.root.agent)
        tree = AgentTree.create(
            request.tree_id or uuid4().hex,
            self.root.node_id,
            definition,
            request.message,
            request.frontier,
        )
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        printed: dict[str, int] = {}

        def observer(current: AgentTree) -> None:
            self._record_tree(current)
            self._echo_node_texts(current, printed)

        completed = await self.runner.run(tree, observer=observer)
        return runtime_views.tree_dict(completed)

    def _echo_node_texts(self, tree: AgentTree, printed: dict[str, int]) -> None:
        # TODO: 后续用 rich 美化输出并加入工具调用 trace
        for node in tree.nodes:
            seen = printed.get(node.node_id, 0)
            for message in node.messages[seen:]:
                if message.role == "assistant" and message.content.strip():
                    self.output(f"Cadence> [{node.definition_id}] {message.content}")
            printed[node.node_id] = len(node.messages)

    async def submit_event(self, event: EnvironmentEvent) -> dict[str, Any]:
        """将外部事实写入 Bot 世界，但不自动唤起新的 AgentTree。"""
        await self.world.initialize()
        commit = await self.world.append_event(event)
        _logger.debug("环境事件已提交 event_id=%s kind=%s", event.event_id, event.kind)
        return runtime_views.commit_dict(commit)

    async def submit_event_values(
        self,
        *,
        event_id: str,
        source: str,
        scope: str,
        kind: str,
        summary: str,
        data: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        when = parse_event_time(occurred_at) if occurred_at else datetime.now(UTC)
        return await self.submit_event(EnvironmentEvent(event_id, source, scope, kind, when, summary, data or {}))

    async def start_tree_from_event(self, event: EnvironmentEvent, *, tree_id: str | None = None) -> dict[str, Any]:
        """显式以一条已提交环境事实启动认知；入口本身不形成自动循环。"""
        await self.submit_event(event)
        frontier = await self.world.head(frozenset({event.scope}))
        tree = self.create_tree(event.summary, tree_id=tree_id, frontier=frontier)
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        return runtime_views.tree_dict(await self.runner.run(tree, observer=self._record_tree))

    async def world_scope(self, scope: str, *, after: int = 0) -> dict[str, Any]:
        """返回一个 scope 从指定序号起的有界提交索引，用于 ops 观察与环境适配器续读。"""
        if after < 0:
            raise ValueError("after 必须是不小于 0 的整数")
        await self.world.initialize()
        delta = await self.world.delta(WorldFrontier({scope: after}), frozenset({scope}))
        return {
            "scope": scope,
            "after": after,
            "frontier": dict(delta.end.positions),
            "has_more": delta.has_more,
            "commits": [runtime_views.commit_dict(commit) for commit in delta.commits],
        }

    async def forest(self, *, limit: int = 64) -> dict[str, Any]:
        """返回 Bot 森林视图：运行期已知树与世界日志推导的持久活动索引。"""
        await self.world.initialize()
        activity = await self.world.tree_index(limit)
        return {
            "runtime": [runtime_views.tree_summary(tree) for tree in reversed(tuple(self._trees.values()))][:limit],
            "journal": [runtime_views.activity_dict(item) for item in activity],
        }

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        self._stop_requester = requester

    def request_shutdown(self) -> None:
        if self._stop_requester is not None:
            self._stop_requester()

    async def dispatch_terminal(self, text: str) -> TerminalResponse:
        command = text.startswith("/")
        input_type = "operation" if command else "message"
        _logger.debug("终端输入开始 input_type=%s", input_type)
        result = (
            await self.ops.route_text(text) if command else await self.ops.execute("POST", "/trees", {"message": text})
        )
        control = {
            OperationControl.NONE: TerminalControl.NONE,
            OperationControl.CLEAR_CONSOLE: TerminalControl.CLEAR,
            OperationControl.SHUTDOWN_PROCESS: TerminalControl.SHUTDOWN,
        }[result.control]
        rendered, tree_failed = runtime_views.terminal_text(result, command=command)
        _logger.debug("终端输入完成 input_type=%s ok=%s code=%s", input_type, result.ok, result.code)
        return TerminalResponse(rendered, control, is_error=not result.ok or tree_failed)

    def runtime_status(self) -> dict[str, Any]:
        statuses = {"running": 0, "completed": 0, "failed": 0}
        for tree in self._trees.values():
            statuses[tree.status.value] += 1
        return {"tree_count": len(self._trees), "trees": statuses}

    def list_trees(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        trees = reversed(tuple(self._trees.values()))
        return [runtime_views.tree_summary(tree) for tree in trees if status is None or tree.status.value == status][
            :limit
        ]

    def tree_detail(self, tree_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        return runtime_views.tree_dict(tree) if tree is not None else None

    def node_detail(self, tree_id: str, node_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        if tree is None:
            return None
        try:
            node = tree.node(node_id)
        except KeyError:
            return None
        return runtime_views.node_dict(node)

    def agent_catalog(self) -> dict[str, Any]:
        return {"agents": [runtime_views.agent_dict(definition) for definition in self.agents.definitions]}

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        try:
            definition = self.agents.get(agent_id)
        except ValueError:
            return None
        return runtime_views.agent_dict(definition)

    def tool_catalog(self) -> dict[str, Any]:
        return {"tools": [runtime_views.tool_dict(definition) for definition in self.runner.tool_definitions]}

    def tool_detail(self, tool_id: str) -> dict[str, Any] | None:
        definition = next((item for item in self.runner.tool_definitions if item.name == tool_id), None)
        return runtime_views.tool_dict(definition) if definition is not None else None

    def mcp_status(self) -> dict[str, Any]:
        snapshot = self.mcp.snapshot()
        return {
            "platform_enabled": snapshot.platform_enabled,
            "restart_required": snapshot.restart_required,
            "tool_ids": list(snapshot.tool_ids),
            "apps": [runtime_views.mcp_app_dict(app) for app in snapshot.apps],
        }

    def mcp_app(self, package: str) -> dict[str, Any] | None:
        snapshot = self.mcp.app(package)
        return runtime_views.mcp_app_dict(snapshot) if snapshot is not None else None

    def prompt_catalog(self) -> dict[str, Any]:
        prompts = self.config.get(PROMPTS_CONFIG)
        return {
            "system": list(prompts.system),
            "agent_prompts": dict(prompts.agent_prompts),
            "max_characters": prompts.max_characters,
        }

    def prompt_detail(self, prompt_id: str) -> dict[str, Any] | None:
        prompts = self.config.get(PROMPTS_CONFIG)
        if prompt_id == "system":
            return {"prompt_id": "system", "fragments": list(prompts.system)}
        content = prompts.agent_prompts.get(prompt_id)
        return {"prompt_id": prompt_id, "content": content} if content is not None else None

    def reload_config(self) -> dict[str, Any]:
        """重新解析全部个人 TOML 并替换运行时配置；不重组任何已装配实例。"""
        config = load_config(self.config.project_root)
        self.config = config
        return {"names": config.names, "sources": [source.name for source in config.sources]}

    def model_catalog(self) -> dict[str, Any]:
        models = self.config.get(MODELS_CONFIG)
        return {
            "providers": [
                {
                    "provider_id": provider_id,
                    "adapter": provider.adapter,
                    "secret_env": provider.secret_env,
                    "base_url": provider.base_url,
                }
                for provider_id, provider in models.providers.items()
            ],
            "endpoints": [
                {"endpoint_id": endpoint_id, "provider": endpoint.provider, "model": endpoint.model}
                for endpoint_id, endpoint in models.endpoints.items()
            ],
        }

    def model_detail(self, endpoint_id: str) -> dict[str, Any] | None:
        models = self.config.get(MODELS_CONFIG)
        endpoint = models.endpoints.get(endpoint_id)
        if endpoint is None:
            return None
        provider = models.providers[endpoint.provider]
        return {
            "endpoint_id": endpoint_id,
            "provider": endpoint.provider,
            "model": endpoint.model,
            "adapter": provider.adapter,
            "secret_env": provider.secret_env,
            "base_url": provider.base_url,
        }

    def utils_status(self) -> dict[str, Any]:
        return runtime_views.utils_status()

    def contracts_status(self) -> dict[str, Any]:
        return runtime_views.contracts_status()

    def cadence_status(self) -> dict[str, Any]:
        return self.cadence.status()

    async def cadence_trigger(self) -> dict[str, Any]:
        await self.world.initialize()
        before = self.cadence.status()
        await self.cadence.evaluate_once()
        return {"before": before, "after": self.cadence.status()}

    async def memory_snapshot(self) -> dict[str, Any]:
        await self.world.initialize()
        snapshot = await self.memory.recall()
        return {
            "window_start": snapshot.window_start.isoformat(),
            "scopes": [
                {
                    "scope": scope.scope,
                    "head": scope.head,
                    "commits": [runtime_views.commit_dict(commit) for commit in scope.commits],
                }
                for scope in snapshot.scopes
            ],
        }

    def console_status(self) -> dict[str, Any]:
        return {
            "enabled": self.root.console_enabled,
            "input_to_worldline": True,
            "output_to_worldline": False,
            "scope": "aurora:console",
        }

    async def world_stream(self, *, after: int = 0, limit: int = 64) -> dict[str, Any]:
        if after < 0:
            raise ValueError("after 必须是不小于 0 的整数")
        await self.world.initialize()
        page = await self.world.stream(after, limit)
        return {
            "after": page.after,
            "end": page.end,
            "has_more": page.has_more,
            "commits": [runtime_views.commit_dict(commit) for commit in page.commits],
        }

    async def world_commit(self, commit_id: str) -> dict[str, Any] | None:
        await self.world.initialize()
        commit = await self.world.commit(commit_id)
        return runtime_views.commit_dict(commit) if commit is not None else None

    async def record_event(
        self,
        *,
        event_id: str,
        kind: str,
        source: str,
        summary: str,
        scope: str,
        data: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """向世界线追加一条提交方已确定 scope 的通用事件。"""
        await self.world.initialize()
        frontier = await self.world.head(frozenset({scope}))
        when = parse_event_time(occurred_at) if occurred_at else datetime.now(UTC)
        commit = await self.world.append_commit(
            commit_id=event_id,
            kind=kind,
            source=source,
            summary=summary,
            scopes=frozenset({scope}),
            based_on=frontier,
            data=data or {},
            occurred_at=when,
        )
        return runtime_views.commit_dict(commit)

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree


def assemble_runtime(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    world: WorldJournal | None = None,
    mcp: McpRuntime | None = None,
    output: Callable[[str], None] = print,
) -> AuroraRuntime:
    """运行全部组件注册器，并取得完整运行时所需实例。"""
    instances: list[InstanceBinding] = []
    if world is not None:
        instances.append((WORLD_JOURNAL, world))
    if mcp is not None:
        instances.append((MCP_RUNTIME, mcp))
    external_tools = (*tuple(tools), *(mcp.tools if mcp is not None else ()))
    assembly = compose_project(config, model, external_tools, instances)
    return AuroraRuntime(
        assembly.get(ENGINE_RUNNER),
        config.get(RUNTIME_CONFIG),
        assembly.get(AGENTS),
        config,
        assembly.get(TERMINAL_CONSOLE),
        assembly.get(WORLD_JOURNAL),
        assembly.get(CADENCE),
        assembly.get(MEMORY),
        assembly.get(MCP_RUNTIME),
        output=output,
    )


async def run_project(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    headless: bool = False,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
    mcp_factory: McpClientFactory | None = None,
) -> AuroraRuntime:
    """先冻结 MCP 工具目录，再组合运行时并让 Console 或停止事件拥有进程前台。"""
    configure_project_logging(config)
    _logger.info("Aurora runtime 启动 headless=%s", headless)
    world = build_world(config)
    mcp: McpRuntime | None = None
    try:
        await world.initialize()
        platform = config.get(PLATFORMS_CONFIG).mcp
        mcp = await prepare_mcp(
            build_mcp_specs(config),
            platform_enabled=platform.enabled,
            world=world,
            factory=mcp_factory,
        )
        _logger.info("MCP 工具目录已冻结 app_count=%d tool_count=%d", len(mcp.snapshot().apps), len(mcp.tools))
        runtime = assemble_runtime(config, model, tools, world=world, mcp=mcp, output=output)
        await _activate_runtime(runtime, mcp)
        _logger.info("Aurora runtime 装配完成")
    except BaseException as error:
        _logger.error("Aurora runtime 启动失败 error_type=%s", type(error).__name__)
        await _close_failed_startup(mcp, world)
        raise

    stop = stop_event or asyncio.Event()
    cadence_task: asyncio.Task[None] | None = None
    panel: PanelRuntime | None = None
    installed = ()
    try:
        runtime.bind_stop_requester(stop.set)
        panel = await run_panel(
            runtime.root.panel,
            runtime.ops,
            storage=config.get(STORAGE_CONFIG),
            project_root=config.project_root,
            profile=runtime.root.profile,
        )
        if runtime.cadence.enabled:
            cadence_task = asyncio.create_task(runtime.cadence.run(stop), name="aurora-cadence")
        installed = install_stop_handlers(stop) if stop_event is None else ()
        if not headless and runtime.root.console_enabled:
            await runtime.console.run(runtime, stop_event=stop, readline=readline, output=output)
        else:
            await stop.wait()
    finally:
        await _shutdown_project(runtime, panel, cadence_task, installed, mcp, world)
    return runtime


async def _close_failed_startup(mcp: McpRuntime | None, world: WorldJournal) -> None:
    if mcp is not None:
        with suppress(Exception):
            await mcp.close()
    with suppress(Exception):
        await world.close()


async def _shutdown_project(
    runtime: AuroraRuntime,
    panel: PanelRuntime | None,
    cadence_task: asyncio.Task[None] | None,
    installed: tuple[InstalledSignal, ...],
    mcp: McpRuntime,
    world: WorldJournal,
) -> None:
    _logger.info("Aurora runtime 开始关闭")
    runtime.bind_stop_requester(None)
    try:
        restore_stop_handlers(installed)
    finally:
        await close_panel(panel)
        if cadence_task is not None:
            cadence_task.cancel()
            await asyncio.gather(cadence_task, return_exceptions=True)
        try:
            await mcp.close()
        finally:
            await world.close()
    _logger.info("Aurora runtime 已关闭")


async def _activate_runtime(runtime: AuroraRuntime, mcp: McpRuntime) -> None:
    """先固定 Cadence cursor，再放行 MCP 业务事件。"""
    if runtime.cadence.enabled:
        await runtime.cadence.initialize()
    await mcp.activate()
