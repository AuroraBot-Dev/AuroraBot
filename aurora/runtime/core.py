"""项目级运行时门面：持有全部已装配实例并实现每个 ops 端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora.configuration import load_config
from aurora.configuration.models import MODELS_CONFIG
from aurora.configuration.prompts import PROMPTS_CONFIG
from aurora.runtime import views
from aurora.runtime.support import parse_event_time
from ops import ConfigAccess, ConfigSourceRef, OpsRuntime
from ops.contracts import OperationControl
from src.console import TerminalConsole, TerminalControl, TerminalResponse
from src.contracts import AgentTree, EnvironmentEvent, WorldFrontier
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora.config import AuroraConfig
    from aurora.configuration.runtime import RuntimeConfig
    from src.agents import AgentCatalog
    from src.cadence import Cadence
    from src.contracts import TreeLaunchRequest, WorldJournal
    from src.engine import AgentTreeRunner
    from src.mcp import McpRuntime
    from src.memory import Memory

_logger = get_logger(__name__)


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
        return views.tree_dict(await self.run(message, tree_id=tree_id))

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
        return views.tree_dict(completed)

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
        return views.commit_dict(commit)

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
        return views.tree_dict(await self.runner.run(tree, observer=self._record_tree))

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
            "commits": [views.commit_dict(commit) for commit in delta.commits],
        }

    async def forest(self, *, limit: int = 64) -> dict[str, Any]:
        """返回 Bot 森林视图：运行期已知树与世界日志推导的持久活动索引。"""
        await self.world.initialize()
        activity = await self.world.tree_index(limit)
        return {
            "runtime": [views.tree_summary(tree) for tree in reversed(tuple(self._trees.values()))][:limit],
            "journal": [views.activity_dict(item) for item in activity],
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
        rendered, tree_failed = views.terminal_text(result, command=command)
        _logger.debug("终端输入完成 input_type=%s ok=%s code=%s", input_type, result.ok, result.code)
        return TerminalResponse(rendered, control, is_error=not result.ok or tree_failed)

    def runtime_status(self) -> dict[str, Any]:
        statuses = {"running": 0, "completed": 0, "failed": 0}
        for tree in self._trees.values():
            statuses[tree.status.value] += 1
        return {"tree_count": len(self._trees), "trees": statuses}

    def list_trees(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        trees = reversed(tuple(self._trees.values()))
        return [views.tree_summary(tree) for tree in trees if status is None or tree.status.value == status][:limit]

    def tree_detail(self, tree_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        return views.tree_dict(tree) if tree is not None else None

    def node_detail(self, tree_id: str, node_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        if tree is None:
            return None
        try:
            node = tree.node(node_id)
        except KeyError:
            return None
        return views.node_dict(node)

    def agent_catalog(self) -> dict[str, Any]:
        return {"agents": [views.agent_dict(definition) for definition in self.agents.definitions]}

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        try:
            definition = self.agents.get(agent_id)
        except ValueError:
            return None
        return views.agent_dict(definition)

    def tool_catalog(self) -> dict[str, Any]:
        return {"tools": [views.tool_dict(definition) for definition in self.runner.tool_definitions]}

    def tool_detail(self, tool_id: str) -> dict[str, Any] | None:
        definition = next((item for item in self.runner.tool_definitions if item.name == tool_id), None)
        return views.tool_dict(definition) if definition is not None else None

    def mcp_status(self) -> dict[str, Any]:
        snapshot = self.mcp.snapshot()
        return {
            "platform_enabled": snapshot.platform_enabled,
            "restart_required": snapshot.restart_required,
            "tool_ids": list(snapshot.tool_ids),
            "apps": [views.mcp_app_dict(app) for app in snapshot.apps],
        }

    def mcp_app(self, package: str) -> dict[str, Any] | None:
        snapshot = self.mcp.app(package)
        return views.mcp_app_dict(snapshot) if snapshot is not None else None

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
        return views.utils_status()

    def contracts_status(self) -> dict[str, Any]:
        return views.contracts_status()

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
                    "commits": [views.commit_dict(commit) for commit in scope.commits],
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
            "commits": [views.commit_dict(commit) for commit in page.commits],
        }

    async def world_commit(self, commit_id: str) -> dict[str, Any] | None:
        await self.world.initialize()
        commit = await self.world.commit(commit_id)
        return views.commit_dict(commit) if commit is not None else None

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
        return views.commit_dict(commit)

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree
