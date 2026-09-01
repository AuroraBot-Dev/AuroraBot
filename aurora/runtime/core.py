"""项目级运行时门面：持有全部已装配实例并实现引擎、进程与配置重载端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from rich.console import Console
from rich.markup import escape as markup_escape

from aurora import views
from aurora.configuration import load_config
from aurora.views import UtilsOps
from ops import ConfigAccess, ConfigSourceRef, OpsRuntime
from ops.contracts import OperationControl
from src.console import TerminalConsole, TerminalControl, TerminalResponse
from src.contracts import AgentTree, EnvironmentEvent, WorldFrontier
from src.utils import bounded_summary, get_logger, parse_event_time

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora.config import AuroraConfig
    from aurora.configuration.runtime import RuntimeConfig
    from aurora.views import ContractsOps
    from ops.contracts import (
        AgentsRuntimePort,
        AiRuntimePort,
        CadenceRuntimePort,
        ConsoleRuntimePort,
        McpRuntimePort,
        MemoryRuntimePort,
        PromptRuntimePort,
        ToolsRuntimePort,
        WorldRuntimePort,
    )
    from src.agents import AgentCatalog
    from src.cadence import Cadence
    from src.contracts import AgentNode, ChatMessage, TreeLaunchRequest, WorldJournal
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
    agents_ops: AgentsRuntimePort
    tools_ops: ToolsRuntimePort
    prompt_ops: PromptRuntimePort
    ai_ops: AiRuntimePort
    world_ops: WorldRuntimePort
    console_ops: ConsoleRuntimePort
    cadence_ops: CadenceRuntimePort
    memory_ops: MemoryRuntimePort
    mcp_ops: McpRuntimePort
    contracts_ops: ContractsOps
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
            agents=self.agents_ops,
            tools=self.tools_ops,
            prompt=self.prompt_ops,
            ai=self.ai_ops,
            world=self.world_ops,
            console=self.console_ops,
            utils=UtilsOps(),
            contracts=self.contracts_ops,
            cadence=self.cadence_ops,
            memory=self.memory_ops,
            mcp=self.mcp_ops,
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
        _logger.info("AgentTree 已提交 tree_id={}", tree.tree_id)
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
        console = Console(highlight=False) if self.output is print else None
        for node in tree.nodes:
            seen = printed.get(node.node_id, 0)
            for message in node.messages[seen:]:
                self._echo_message(node, message, console)
            printed[node.node_id] = len(node.messages)

    def _echo_message(self, node: AgentNode, message: ChatMessage, console: Console | None) -> None:
        tag = node.definition_id
        if message.role == "assistant":
            if message.content.strip():
                self._echo_line("Cadence>", tag, message.content, console)
            for call in message.tool_calls:
                self._echo_line("→", tag, call.name, console, indent=True)
        elif message.role == "tool":
            summary = bounded_summary((message.content,))
            label = "失败" if message.is_error else "←"
            self._echo_line(label, tag, summary, console, indent=True)

    def _echo_line(
        self,
        prefix: str,
        tag: str,
        content: str,
        console: Console | None,
        *,
        indent: bool = False,
    ) -> None:
        marker = f"{'  ' if indent else ''}{prefix}"
        if console is None:
            self.output(f"{marker} [{tag}] {content}")
            return
        console.print(
            f"[bold]{marker}[/bold] [cyan]\\[{markup_escape(tag)}][/cyan] {markup_escape(content)}",
            highlight=False,
        )

    async def submit_event(self, event: EnvironmentEvent) -> dict[str, Any]:
        """将外部事实写入 Bot 世界，但不自动唤起新的 AgentTree。"""
        await self.world.initialize()
        commit = await self.world.append_event(event)
        _logger.debug("环境事件已提交 event_id={} kind={}", event.event_id, event.kind)
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
        _logger.debug("终端输入开始 input_type={}", input_type)
        result = (
            await self.ops.route_text(text) if command else await self.ops.execute("POST", "/trees", {"message": text})
        )
        control = {
            OperationControl.NONE: TerminalControl.NONE,
            OperationControl.CLEAR_CONSOLE: TerminalControl.CLEAR,
            OperationControl.SHUTDOWN_PROCESS: TerminalControl.SHUTDOWN,
        }[result.control]
        rendered, tree_failed = views.terminal_text(result, command=command)
        _logger.debug("终端输入完成 input_type={} ok={} code={}", input_type, result.ok, result.code)
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

    def reload_config(self) -> dict[str, Any]:
        """重新解析全部个人 TOML 并替换运行时配置；不重组任何已装配实例。"""
        config = load_config(self.config.project_root)
        self.config = config
        return {"names": config.names, "sources": [source.name for source in config.sources]}

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree
