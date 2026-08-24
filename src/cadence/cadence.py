"""世界线驱动的节律与 AgentTree 唤起策略。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.contracts import TreeLauncher, TreeLaunchRequest, WorldCommit, WorldFrontier, WorldReader, WorldWriter
from src.utils import get_logger

_logger = get_logger(__name__)

CADENCE_SCOPE = "aurora:cadence"
CADENCE_TICK = "cadence.tick"
CADENCE_TREE_PLANNED = "cadence.tree_planned"
CADENCE_TREE_FAILED = "cadence.tree_failed"

DEFAULT_EVOKE_EVERY = 5
DEFAULT_TICK_EVERY = timedelta(hours=1)
DEFAULT_POLL_INTERVAL = 0.25
DEFAULT_PAGE_SIZE = 64
DEFAULT_LAUNCH_MESSAGE = "节律唤起：请初筛最近一小时的世界活动。"


class Cadence:
    """每 ``evoke_every`` 个非 engine 世界提交唤起一棵树，并按固定节律提交 tick。"""

    def __init__(
        self,
        reader: WorldReader,
        writer: WorldWriter,
        *,
        launcher: TreeLauncher | None = None,
        agent: str | None = None,
        enabled: bool = False,
        evoke_every: int = DEFAULT_EVOKE_EVERY,
        tick_every: timedelta = DEFAULT_TICK_EVERY,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if evoke_every <= 0:
            raise ValueError("evoke_every must be positive")
        if tick_every <= timedelta(0):
            raise ValueError("tick_every must be positive")
        if poll_interval <= 0 or page_size <= 0:
            raise ValueError("poll_interval and page_size must be positive")
        self._reader = reader
        self._writer = writer
        self._launcher = launcher
        self.agent = agent
        self.enabled = enabled
        self.evoke_every = evoke_every
        self.tick_every = tick_every
        self.poll_interval = poll_interval
        self.page_size = page_size
        self._cursor = 0
        self._pending = 0
        self._next_tick = 0.0

    def bind_launcher(self, launcher: TreeLauncher) -> None:
        self._launcher = launcher

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "agent": self.agent,
            "cursor": self._cursor,
            "pending": self._pending,
            "evoke_every": self.evoke_every,
            "tick_seconds": int(self.tick_every.total_seconds()),
            "poll_seconds": self.poll_interval,
            "page_size": self.page_size,
            "next_tick": self._next_tick,
        }

    async def run(self, stop_event: asyncio.Event) -> None:
        self._cursor = await self._reader.cursor()
        self._next_tick = asyncio.get_running_loop().time() + self.tick_every.total_seconds()
        _logger.info("Cadence 启动 cursor=%d evoke_every=%d", self._cursor, self.evoke_every)
        while not stop_event.is_set():
            if asyncio.get_running_loop().time() >= self._next_tick:
                await self._submit_tick()
                self._next_tick = asyncio.get_running_loop().time() + self.tick_every.total_seconds()
            await self.evaluate_once()
            if not stop_event.is_set():
                await asyncio.sleep(self.poll_interval)
        _logger.info("Cadence 已停止 cursor=%d", self._cursor)

    async def evaluate_once(self) -> None:
        """消费一页新事件；最多执行一次唤起判断。"""
        page = await self._reader.stream(self._cursor, self.page_size)
        if not page.commits:
            return
        _logger.debug("Cadence 消费世界提交 commit_count=%d has_more=%s", len(page.commits), page.has_more)
        for commit in page.commits:
            self._cursor = page.end
            if not self._counts(commit):
                continue
            self._pending += 1
            if self._pending >= self.evoke_every:
                self._pending = 0
                await self._evoke(commit)
                return
        if page.has_more:
            await self.evaluate_once()

    async def _submit_tick(self) -> None:
        now = datetime.now(UTC)
        await self._writer.append_commit(
            commit_id=f"cadence:tick:{now.isoformat()}",
            kind=CADENCE_TICK,
            source="cadence",
            summary=f"节律 tick：{now.isoformat()}",
            scopes=frozenset({CADENCE_SCOPE}),
            based_on=await self._frontier(),
            data={"occurred_at": now.isoformat()},
            occurred_at=now,
        )
        _logger.debug("Cadence tick 已提交")

    async def _evoke(self, caused_by: WorldCommit) -> None:
        assert self._launcher is not None, "cadence launcher has not been bound"
        tree_id = f"cadence:{uuid4().hex}"
        try:
            await self._writer.append_commit(
                commit_id=f"cadence:tree:{tree_id}:planned",
                kind=CADENCE_TREE_PLANNED,
                source="cadence",
                summary="节律策略决定唤起一棵 AgentTree",
                scopes=frozenset({CADENCE_SCOPE}),
                based_on=await self._frontier(),
                data={
                    "tree_id": tree_id,
                    "agent": self.agent,
                    "caused_by": caused_by.commit_id,
                    "evoke_every": self.evoke_every,
                },
            )
            await self._launcher.launch_tree(
                TreeLaunchRequest(
                    DEFAULT_LAUNCH_MESSAGE,
                    tree_id=tree_id,
                    agent=self.agent,
                    caused_by=caused_by.commit_id,
                )
            )
            _logger.info("Cadence 已唤起 AgentTree tree_id=%s", tree_id)
        except Exception as error:  # noqa: BLE001 - 节律后台不得因唤起失败而退出
            _logger.error("Cadence 唤起失败 tree_id=%s error_type=%s", tree_id, type(error).__name__)
            await self._writer.append_commit(
                commit_id=f"cadence:tree:{tree_id}:failed",
                kind=CADENCE_TREE_FAILED,
                source="cadence",
                summary=f"节律唤起失败：{error}",
                scopes=frozenset({CADENCE_SCOPE}),
                based_on=await self._frontier(),
                data={"tree_id": tree_id, "error": str(error)},
            )
        finally:
            # 跳过本次唤起产生的 engine 事件，避免树活动重新触发下一棵树。
            self._cursor = await self._reader.cursor()

    async def _frontier(self) -> WorldFrontier:
        return await self._reader.head(frozenset({CADENCE_SCOPE}))

    @staticmethod
    def _counts(commit: WorldCommit) -> bool:
        return not commit.kind.startswith("engine.")
