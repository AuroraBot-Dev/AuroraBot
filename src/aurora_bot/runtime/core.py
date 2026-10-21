"""项目级进程门面：持有已装配能力并请求认知。

门面只负责认知运行与事实提交；终端文本渲染与本地命令分派分别由
``CognitionTextPresenter`` 与 ``TerminalCommandDispatcher`` 承担。
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora_bot.contracts import CognitionRequest, CognitionResult, EnvironmentEvent, WorldCommit, WorldFrontier
from aurora_bot.runtime.events import RUNTIME_INPUT, RUNTIME_SCOPE
from aurora_bot.runtime.presenter import CognitionTextPresenter
from aurora_bot.runtime.resource_commands import ResourceCommands
from aurora_bot.runtime.terminal import TerminalCommandDispatcher
from aurora_bot.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_bot.contracts import FrontBinding
    from aurora_bot.contracts.pkgs.engine import CognitionRunner
    from aurora_bot.contracts.pkgs.operations import OperationRegistry
    from aurora_bot.contracts.pkgs.world import WorldJournal
    from aurora_bot.kernel import Assembly
    from aurora_bot.runtime.config import RuntimeConfig

_logger = get_logger(__name__)


class AuroraRuntime:
    """保留项目级运行边界；协作者由装配层从 Assembly 注入。"""

    def __init__(
        self,
        assembly: Assembly,
        *,
        runner: CognitionRunner,
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
        self.root = root
        self.world = world
        self.output = output
        self.front_bindings = front_bindings
        self.presenter = CognitionTextPresenter(output)
        self.terminal = TerminalCommandDispatcher(self.run_from_commit, ResourceCommands(operations, bot_id))
        self._counts: Counter[str] = Counter()
        self._cognition_lock = asyncio.Lock()

    async def run(self, message: str, *, run_id: str | None = None) -> CognitionResult:
        """直接文本输入也先提交到世界，再进入统一认知入口。"""
        if not message.strip():
            raise ValueError("运行输入不能为空")
        await self.world.initialize()
        if run_id is not None:
            await self._require_new_run_id(run_id)
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
        return await self.run_from_commit(commit, run_id=run_id)

    async def run_from_commit(self, commit: WorldCommit, *, run_id: str | None = None) -> CognitionResult:
        """以已提交事实启动认知，不重复提交输入或读取更新后的世界 head。"""
        return await self._run_request(
            CognitionRequest(
                commit.summary,
                run_id=run_id,
                frontier=WorldFrontier(commit.scopes),
                caused_by=commit.commit_id,
                memory_scopes=frozenset(commit.scopes),
            ),
        )

    async def launch(self, request: CognitionRequest) -> CognitionResult:
        """cadence 等主动策略的统一唤起入口。"""
        return await self._run_request(request, echo=True)

    async def _run_request(self, request: CognitionRequest, *, echo: bool = False) -> CognitionResult:
        """让主体的主要认知有序执行，外部事实仍可持续提交。"""
        async with self._cognition_lock:
            request = replace(
                request,
                run_id=request.run_id or uuid4().hex,
                agent=request.agent or self.root.agent,
                node_id=self.root.node_id,
            )
            assert request.run_id is not None
            await self.world.initialize()
            await self._require_new_run_id(request.run_id)
            self._counts["running"] += 1
            presenter = CognitionTextPresenter(self.output)
            try:
                result = await self.runner.execute(request, observer=presenter.echo if echo else None)
                if result.run_id != request.run_id:
                    raise ValueError("认知结果与请求身份不一致")
            except asyncio.CancelledError:
                self._counts["interrupted"] += 1
                raise
            except Exception:
                self._counts["failed"] += 1
                raise
            else:
                self._counts[result.status] += 1
                return result
            finally:
                self._counts["running"] -= 1

    async def _require_new_run_id(self, run_id: str) -> None:
        """持久开始事实同样占用实例身份，重启不赋予再次执行的含义。"""
        if await self.world.commit(f"{run_id}:tree:started") is not None:
            raise ValueError(f"认知运行已存在：{run_id}")

    async def submit_event(self, event: EnvironmentEvent) -> WorldCommit:
        """将外部事实写入 Bot 世界，但不自动唤起新的认知执行。"""
        await self.world.initialize()
        commit = await self.world.append_event(event)
        _logger.debug("环境事件已提交 event_id={} kind={}", event.event_id, event.kind)
        return commit

    async def run_from_event(self, event: EnvironmentEvent, *, run_id: str | None = None) -> CognitionResult:
        """显式以一条已提交环境事实启动认知；入口本身不形成自动循环。"""
        commit = await self.submit_event(event)
        return await self.run_from_commit(commit, run_id=run_id)

    def runtime_status(self) -> dict[str, Any]:
        statuses = {name: self._counts[name] for name in ("running", "completed", "failed", "interrupted")}
        return {"run_count": sum(statuses.values()), "runs": statuses}
