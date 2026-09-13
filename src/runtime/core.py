"""项目级进程门面：持有已装配能力并运行 AgentTree。

门面只负责认知运行与事实提交；终端文本渲染与本地命令分派分别由
``TreeTextPresenter`` 与 ``TerminalCommandDispatcher`` 承担。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.contracts import AgentTree, EnvironmentEvent, WorldCommit, WorldFrontier
from src.runtime.presenter import TreeTextPresenter
from src.runtime.terminal import TerminalCommandDispatcher
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.contracts import (
        AgentCatalog,
        AgentTreeRunner,
        FrontBinding,
        RuntimeConfig,
        TerminalConsole,
        TreeLaunchRequest,
        WorldJournal,
    )
    from src.kernel import Assembly

_logger = get_logger(__name__)


class AuroraRuntime:
    """保留项目级运行边界；协作者由装配层从 Assembly 注入。"""

    def __init__(
        self,
        assembly: Assembly,
        *,
        runner: AgentTreeRunner,
        agents: AgentCatalog,
        root: RuntimeConfig,
        console: TerminalConsole,
        world: WorldJournal,
        output: Callable[[str], None] = print,
        front_bindings: tuple[FrontBinding, ...] = (),
    ) -> None:
        self.assembly = assembly
        self.settings = assembly.settings
        self.runner = runner
        self.agents = agents
        self.root = root
        self.console = console
        self.world = world
        self.output = output
        self.front_bindings = front_bindings
        self.presenter = TreeTextPresenter(output)
        self.terminal = TerminalCommandDispatcher(self.run)
        self._trees: dict[str, AgentTree] = {}

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

        def observer(current: AgentTree) -> None:
            self._record_tree(current)
            self.presenter.echo(current)

        return await self.runner.run(tree, observer=observer)

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

    def runtime_status(self) -> dict[str, Any]:
        statuses = {"running": 0, "completed": 0, "failed": 0}
        for tree in self._trees.values():
            statuses[tree.status.value] += 1
        return {"tree_count": len(self._trees), "trees": statuses}

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree
