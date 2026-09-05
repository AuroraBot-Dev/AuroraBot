"""项目级进程门面：持有已装配实例并运行 AgentTree。

本模块不读取任何 ``aurora.composition`` 键或 ``aurora.configuration`` 规格；
协作者由 ``aurora.runtime.assembly`` 从单一 ``AuroraAssembly`` 解析后注入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from rich.console import Console
from rich.markup import escape as markup_escape

from src.console import TerminalControl, TerminalResponse
from src.contracts import AgentTree, EnvironmentEvent, WorldCommit, WorldFrontier
from src.utils import bounded_summary, get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aurora.composer import AuroraAssembly
    from aurora.configuration.runtime import RuntimeConfig
    from src.agents import AgentCatalog
    from src.cadence import Cadence
    from src.console import TerminalConsole
    from src.contracts import AgentNode, ChatMessage, TreeLaunchRequest, WorldJournal
    from src.engine import AgentTreeRunner
    from src.mcp import McpRuntime
    from src.memory import Memory

_logger = get_logger(__name__)


class AuroraRuntime:
    """保留项目级运行边界；协作者由装配层从 Assembly 注入。"""

    def __init__(
        self,
        assembly: AuroraAssembly,
        *,
        runner: AgentTreeRunner,
        agents: AgentCatalog,
        root: RuntimeConfig,
        console: TerminalConsole,
        world: WorldJournal,
        cadence: Cadence,
        memory: Memory,
        mcp: McpRuntime,
        output: Callable[[str], None] = print,
    ) -> None:
        self.assembly = assembly
        self.config = assembly.config
        self.runner = runner
        self.agents = agents
        self.root = root
        self.console = console
        self.world = world
        self.cadence = cadence
        self.memory = memory
        self.mcp = mcp
        self.output = output
        self._trees: dict[str, AgentTree] = {}
        self._serve_requester: Callable[[], Awaitable[str]] | None = None

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

    async def launch_tree(self, request: TreeLaunchRequest) -> AgentTree:
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

        return await self.runner.run(tree, observer=observer)

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

    async def submit_event(self, event: EnvironmentEvent) -> WorldCommit:
        """将外部事实写入 Bot 世界，但不自动唤起新的 AgentTree。"""
        await self.world.initialize()
        commit = await self.world.append_event(event)
        _logger.debug("环境事件已提交 event_id={} kind={}", event.event_id, event.kind)
        return commit

    async def start_tree_from_event(self, event: EnvironmentEvent, *, tree_id: str | None = None) -> AgentTree:
        """显式以一条已提交环境事实启动认知；入口本身不形成自动循环。"""
        await self.submit_event(event)
        frontier = await self.world.head(frozenset({event.scope}))
        tree = self.create_tree(event.summary, tree_id=tree_id, frontier=frontier)
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        return await self.runner.run(tree, observer=self._record_tree)

    def bind_serve_requester(self, requester: Callable[[], Awaitable[str]] | None) -> None:
        self._serve_requester = requester

    async def dispatch_terminal(self, text: str) -> TerminalResponse:
        input_type = "command" if text.startswith("/") else "message"
        _logger.debug("终端输入开始 input_type={}", input_type)
        if text in {"/help", "/h"}:
            return TerminalResponse("本地命令：/help /clear /quit /serve")
        if text in {"/clear", "/cls"}:
            return TerminalResponse(control=TerminalControl.CLEAR)
        if text in {"/quit", "/exit", "/q"}:
            return TerminalResponse("正在停止。", TerminalControl.SHUTDOWN)
        if text == "/serve":
            return await self._serve_panel()
        if text.startswith("/"):
            return TerminalResponse("未知本地命令；输入 /help 查看命令。", is_error=True)

        tree = await self.run(text)
        root = tree.node(tree.root_id)
        failed = root.status.value == "failed"
        rendered = root.error if failed else root.result
        _logger.debug("终端输入完成 input_type={} tree_status={}", input_type, tree.status.value)
        return TerminalResponse(rendered, is_error=failed)

    async def _serve_panel(self) -> TerminalResponse:
        if self._serve_requester is None:
            return TerminalResponse("Panel 后端当前不可启动。", is_error=True)
        try:
            return TerminalResponse(await self._serve_requester())
        except (OSError, RuntimeError, ValueError) as error:
            _logger.error("Panel 后端启动失败 error_type={}", type(error).__name__)
            return TerminalResponse(f"Panel 后端启动失败：{error}", is_error=True)

    def runtime_status(self) -> dict[str, Any]:
        statuses = {"running": 0, "completed": 0, "failed": 0}
        for tree in self._trees.values():
            statuses[tree.status.value] += 1
        return {"tree_count": len(self._trees), "trees": statuses}

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree
