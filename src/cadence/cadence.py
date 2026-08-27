"""世界线驱动的节律与 AgentTree 唤起策略。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.contracts import (
    MCP_EVENT_RECEIVED,
    TreeLauncher,
    TreeLaunchRequest,
    WorldCommit,
    WorldFrontier,
    WorldReader,
    WorldWriter,
)
from src.utils import get_logger

_logger = get_logger(__name__)

CADENCE_SCOPE = "aurora:cadence"
CADENCE_TICK = "cadence.tick"
CADENCE_TREE_PLANNED = "cadence.tree_planned"
CADENCE_TREE_FAILED = "cadence.tree_failed"

DEFAULT_EVOKE_EVERY = 5
DEFAULT_TICK_EVERY = timedelta(hours=1)
DEFAULT_POLL_INTERVAL = 0.25
DEFAULT_PAGE_SIZE = 1
DEFAULT_LAUNCH_MESSAGE = "节律唤起：请初筛最近时间窗口内的世界活动。"
_REACTIVE_MESSAGE_PREFIX = "即时会话事件：可以只生成回复正文，也可以用发送工具按人类节奏分多条发送。"
_MCP_SCOPE_PREFIX = "aurora:mcp:"


@dataclass(frozen=True, slots=True)
class ReactiveRule:
    """把已提交的外部事件匹配到一个即时会话 Agent。"""

    source: str
    event_kind: str
    agent: str
    contains_any: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.source.strip(), self.event_kind.strip(), self.agent.strip())):
            raise ValueError("ReactiveRule requires source, event_kind and agent")
        terms = tuple(term.strip() for term in self.contains_any)
        if any(not term for term in terms):
            raise ValueError("ReactiveRule contains_any must not contain empty text")
        object.__setattr__(self, "contains_any", terms)

    def matches(self, commit: WorldCommit) -> bool:
        if commit.kind != MCP_EVENT_RECEIVED or commit.source != self.source:
            return False
        if commit.data.get("event_kind") != self.event_kind:
            return False
        return not self.contains_any or any(term in commit.summary for term in self.contains_any)


class Cadence:
    """即时规则按提交唤起会话树，未匹配事件按阈值唤起批量树，并按固定节律提交 tick。"""

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
        reactive_rules: tuple[ReactiveRule, ...] = (),
    ) -> None:
        if evoke_every <= 0:
            raise ValueError("evoke_every must be positive")
        if tick_every <= timedelta(0):
            raise ValueError("tick_every must be positive")
        if poll_interval <= 0 or page_size != 1:
            raise ValueError("poll_interval must be positive and page_size must equal one")
        self._reader = reader
        self._writer = writer
        self._launcher = launcher
        self.agent = agent
        self.enabled = enabled
        self.evoke_every = evoke_every
        self.tick_every = tick_every
        self.poll_interval = poll_interval
        self.page_size = page_size
        self.reactive_rules = tuple(reactive_rules)
        self._cursor = 0
        self._pending = 0
        self._next_tick = 0.0
        self._initialized = False

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
            "reactive_rule_count": len(self.reactive_rules),
            "next_tick": self._next_tick,
        }

    async def initialize(self) -> None:
        """在外部事件入口激活前固定起始 cursor，避免启动窗口漏事件。"""
        if self._initialized:
            return
        self._cursor = await self._reader.cursor()
        self._next_tick = asyncio.get_running_loop().time() + self.tick_every.total_seconds()
        self._initialized = True

    async def run(self, stop_event: asyncio.Event) -> None:
        await self.initialize()
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
        while True:
            page = await self._reader.stream(self._cursor, self.page_size)
            if not page.commits:
                return
            if len(page.commits) != 1:
                raise RuntimeError("Cadence stream page 必须恰好包含一条提交")
            commit = page.commits[0]
            self._cursor = page.end
            rule = next((candidate for candidate in self.reactive_rules if candidate.matches(commit)), None)
            if rule is not None:
                await self._evoke(
                    commit,
                    agent=rule.agent,
                    message=_reactive_message(commit),
                    frontier=_business_frontier(commit),
                    mode="reactive",
                )
                return
            if not self._counts(commit):
                continue
            self._pending += 1
            if self._pending >= self.evoke_every:
                self._pending = 0
                await self._evoke(
                    commit,
                    agent=self.agent,
                    message=DEFAULT_LAUNCH_MESSAGE,
                    frontier=WorldFrontier(),
                    mode="batch",
                )
                return

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

    async def _evoke(
        self,
        caused_by: WorldCommit,
        *,
        agent: str | None,
        message: str,
        frontier: WorldFrontier,
        mode: str,
    ) -> None:
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
                    "agent": agent,
                    "caused_by": caused_by.commit_id,
                    "evoke_every": self.evoke_every,
                    "mode": mode,
                },
            )
            await self._launcher.launch_tree(
                TreeLaunchRequest(
                    message,
                    tree_id=tree_id,
                    agent=agent,
                    frontier=frontier,
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

    async def _frontier(self) -> WorldFrontier:
        return await self._reader.head(frozenset({CADENCE_SCOPE}))

    @staticmethod
    def _counts(commit: WorldCommit) -> bool:
        return commit.kind == MCP_EVENT_RECEIVED


def _business_frontier(commit: WorldCommit) -> WorldFrontier:
    positions = {
        scope: sequence for scope, sequence in commit.scopes.items() if not scope.startswith(_MCP_SCOPE_PREFIX)
    }
    return WorldFrontier(positions or commit.scopes)


def _reactive_message(commit: WorldCommit) -> str:
    event_data = commit.data.get("data")
    details = {
        "source": commit.source,
        "summary": commit.summary,
        "event_kind": commit.data.get("event_kind"),
        "event_data": event_data if isinstance(event_data, Mapping) else {},
    }
    return f"{_REACTIVE_MESSAGE_PREFIX}\n{json.dumps(details, ensure_ascii=False, separators=(',', ':'))}"
