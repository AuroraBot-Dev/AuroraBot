"""项目级进程门面：持有已装配能力并运行 AgentTree。

门面只负责认知运行与事实提交；终端文本渲染与本地命令分派分别由
``TreeTextPresenter`` 与 ``TerminalCommandDispatcher`` 承担。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.contracts import AgentTree, EnvironmentEvent, TreeLaunchRequest, WorldCommit, WorldFrontier
from src.runtime.events import RUNTIME_INPUT, RUNTIME_SCOPE
from src.runtime.presenter import TreeTextPresenter
from src.runtime.resource_commands import ResourceCommands
from src.runtime.terminal import TerminalCommandDispatcher
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.contracts import FrontBinding
    from src.contracts.pkgs.agents import AgentCatalog
    from src.contracts.pkgs.engine import AgentTreeRunner
    from src.contracts.pkgs.operations import OperationRegistry
    from src.contracts.pkgs.world import WorldJournal
    from src.kernel import Assembly
    from src.runtime.config import RuntimeConfig

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
        world: WorldJournal,
        operations: OperationRegistry,
        bot_id: str,
        output: Callable[[str], None] = print,
        front_bindings: tuple[FrontBinding, ...] = (),
    ) -> None:
        self.assembly = assembly
        self.settings = assembly.settings
        self.runner = runner
        self.agents = agents
        self.root = root
        self.world = world
        self.output = output
        self.front_bindings = front_bindings
        self.presenter = TreeTextPresenter(output)
        self.terminal = TerminalCommandDispatcher(self.run_from_commit, ResourceCommands(operations, bot_id))
        self._trees: dict[str, AgentTree] = {}
        self._cognition_lock = asyncio.Lock()

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
        """直接文本输入也先提交到世界，再进入统一认知入口。"""
        if not message.strip():
            raise ValueError("运行输入不能为空")
        if tree_id is not None and tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree_id}")
        await self.world.initialize()
        if tree_id is not None:
            await self._require_new_tree_id(tree_id)
        commit = await self.world.append_commit(
            commit_id=f"runtime:{uuid4().hex}",
            kind=RUNTIME_INPUT,
            source="runtime",
            summary=message,
            scopes=frozenset({RUNTIME_SCOPE}),
            based_on=WorldFrontier(),
            data={"text": message},
            occurred_at=datetime.now(UTC),
        )
        return await self.run_from_commit(commit, tree_id=tree_id)

    async def run_from_commit(self, commit: WorldCommit, *, tree_id: str | None = None) -> AgentTree:
        """以已提交事实启动认知，不重复提交输入或读取更新后的世界 head。"""
        return await self._run_request(
            TreeLaunchRequest(
                commit.summary,
                tree_id=tree_id,
                frontier=WorldFrontier(commit.scopes),
                caused_by=commit.commit_id,
                memory_scopes=frozenset(commit.scopes),
            ),
        )

    async def launch_tree(self, request: TreeLaunchRequest) -> AgentTree:
        """cadence 等主动策略的统一唤起入口。"""
        return await self._run_request(request, echo=True)

    async def _run_request(self, request: TreeLaunchRequest, *, echo: bool = False) -> AgentTree:
        """让主体的主要认知有序执行，外部事实仍可持续提交。"""
        async with self._cognition_lock:
            return await self._execute_request(request, echo=echo)

    async def _execute_request(self, request: TreeLaunchRequest, *, echo: bool = False) -> AgentTree:
        """构建并记录一棵具有独立身份的认知树。"""
        tree = AgentTree.create(
            request.tree_id or uuid4().hex,
            self.root.node_id,
            self.agents.get(request.agent or self.root.agent),
            request.message,
            request.frontier,
            caused_by=request.caused_by,
            memory_scopes=request.memory_scopes,
            focus_goal_ids=request.focus_goal_ids,
        )
        await self.world.initialize()
        await self._require_new_tree_id(tree.tree_id)

        def observer(current: AgentTree) -> None:
            self._record_tree(current)
            if echo:
                self.presenter.echo(current)

        _logger.info("AgentTree 已提交 tree_id={}", tree.tree_id)
        return await self.runner.run(tree, observer=observer)

    async def _require_new_tree_id(self, tree_id: str) -> None:
        """持久开始事实同样占用实例身份，重启不赋予再次执行的含义。"""
        if tree_id in self._trees or await self.world.commit(f"{tree_id}:tree:started") is not None:
            raise ValueError(f"AgentTree 已存在：{tree_id}")

    async def submit_event(self, event: EnvironmentEvent) -> WorldCommit:
        """将外部事实写入 Bot 世界，但不自动唤起新的 AgentTree。"""
        await self.world.initialize()
        commit = await self.world.append_event(event)
        _logger.debug("环境事件已提交 event_id={} kind={}", event.event_id, event.kind)
        return commit

    async def start_tree_from_event(self, event: EnvironmentEvent, *, tree_id: str | None = None) -> AgentTree:
        """显式以一条已提交环境事实启动认知；入口本身不形成自动循环。"""
        commit = await self.submit_event(event)
        return await self.run_from_commit(commit, tree_id=tree_id)

    def runtime_status(self) -> dict[str, Any]:
        statuses = {"running": 0, "completed": 0, "failed": 0}
        for tree in self._trees.values():
            statuses[tree.status.value] += 1
        return {"tree_count": len(self._trees), "trees": statuses}

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree
