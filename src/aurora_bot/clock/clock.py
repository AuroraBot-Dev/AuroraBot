"""兑现持久活动安排，并在重启后核对交付结果。"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aurora_bot.contracts import TreeLaunchRequest, TreeStatus
from aurora_bot.contracts.bot import BotChange, StateConflictError, WakePlan, WakeStatus
from aurora_bot.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_bot.contracts.pkgs.bot import BotStateStore
    from aurora_bot.contracts.pkgs.runtime import TreeLauncher
    from aurora_bot.contracts.pkgs.world import WorldReader

_logger = get_logger(__name__)


class PersistentBotClock:
    """时间服务兑现既有选择，节律策略可独立决定新的推理机会。"""

    def __init__(
        self,
        state: BotStateStore,
        world: WorldReader,
        *,
        poll_seconds: float = 0.25,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """注入主体与经历记录，使用单调等待和持久绝对时间。"""
        if poll_seconds <= 0:
            raise ValueError("时间检查间隔必须大于零")
        self._state = state
        self._world = world
        self._poll_seconds = poll_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._launcher: TreeLauncher | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    def bind_launcher(self, launcher: TreeLauncher) -> None:
        """接入已装配的主体认知入口。"""
        self._launcher = launcher

    async def initialize(self) -> None:
        """重启时核对运行日志，不重放已经开始且结果未知的认知。"""
        if self._initialized:
            return
        snapshot = await self._state.snapshot()
        for wake in snapshot.wakes:
            if wake.status is not WakeStatus.RUNNING:
                continue
            tree_id = self.tree_id(wake)
            completed = await self._world.commit(f"{tree_id}:tree:completed")
            failed = await self._world.commit(f"{tree_id}:tree:failed")
            started = await self._world.commit(f"{tree_id}:tree:started")
            if completed is not None:
                await self._settle(wake, WakeStatus.COMPLETED, "重启后已核对认知完成记录")
            elif failed is not None:
                await self._settle(wake, WakeStatus.FAILED, failed.summary)
            elif started is not None:
                await self._settle(wake, WakeStatus.INTERRUPTED, "认知已经开始，完成结果未知；需要核对行动结果")
        self._initialized = True

    async def evaluate_once(self, now: datetime | None = None) -> None:
        """兑现一次到期活动，交付前先持久记录运行身份。"""
        async with self._lock:
            await self.initialize()
            if self._launcher is None:
                raise RuntimeError("Bot 时间服务尚未绑定认知入口")
            observed_at = now or self._now()
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ValueError("检查时间必须包含时区")
            snapshot = await self._state.snapshot()
            due = sorted(
                (
                    wake
                    for wake in snapshot.wakes
                    if wake.status is WakeStatus.RUNNING
                    or (wake.status is WakeStatus.PENDING and wake.due_at <= observed_at)
                ),
                key=lambda wake: (wake.due_at, wake.wake_id),
            )
            if not due:
                return
            wake = due[0]
            if wake.status is WakeStatus.PENDING:
                wake = replace(wake, status=WakeStatus.RUNNING)
                try:
                    await self._state.apply(BotChange(f"wake:claim:{wake.wake_id}", snapshot.version, wakes=(wake,)))
                except StateConflictError:
                    return
            await self._launch(wake)

    async def run(self, stop: asyncio.Event) -> None:
        """使用可取消等待维持时间检查，不占用认知预算。"""
        await self.initialize()
        while not stop.is_set():
            await self.evaluate_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                continue

    def tree_id(self, wake: WakePlan) -> str:
        """从主体和安排身份确定唯一认知运行身份。"""
        identity = f"{self._state.bot_id}\n{wake.wake_id}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"wake:{digest}"

    async def _launch(self, wake: WakePlan) -> None:
        """运行一次认知并保存结果；取消时保留交付状态供恢复核对。"""
        assert self._launcher is not None
        snapshot = await self._state.snapshot()
        frontier = await self._world.head(frozenset({self._state.scope}))
        goal = f"\n关联目标：{wake.goal_id}" if wake.goal_id else ""
        request = TreeLaunchRequest(
            f"这是你安排的未来检查：{wake.message}{goal}\n请先核对自己的目标、检查点和未确认行动，再决定继续、调整或结束。",
            tree_id=self.tree_id(wake),
            frontier=frontier,
            caused_by=f"{snapshot.bot_id}:state:{snapshot.version}",
            focus_goal_ids=(wake.goal_id,) if wake.goal_id is not None else (),
        )
        try:
            result = await self._launcher.launch_tree(request)
        except Exception as error:
            _logger.exception("未来活动执行失败 wake_id={}", wake.wake_id)
            await self._settle(wake, WakeStatus.FAILED, str(error))
            return
        status = WakeStatus.COMPLETED if result.status is TreeStatus.COMPLETED else WakeStatus.FAILED
        await self._settle(wake, status, f"认知运行状态：{result.status.value}")

    async def _settle(self, wake: WakePlan, status: WakeStatus, detail: str) -> None:
        """保留并发目标修改，直到当前安排的结果得到确认。"""
        while True:
            snapshot = await self._state.snapshot()
            current = snapshot.wake(wake.wake_id)
            if current.status is not WakeStatus.RUNNING:
                return
            try:
                await self._state.apply(
                    BotChange(
                        f"wake:result:{wake.wake_id}",
                        snapshot.version,
                        wakes=(replace(current, status=status, detail=detail),),
                    )
                )
            except StateConflictError:
                continue
            return
