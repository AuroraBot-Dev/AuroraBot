"""构造并导出 ``src.world`` 的项目实例。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.configuration.storage import STORAGE_CONFIG, resolve_directory
from aurora.views import commit_dict
from src.contracts import WorldJournal
from src.utils import parse_event_time
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig


class WorldOps:
    """WorldJournal 的窄 ops 端口适配器。"""

    def __init__(self, world: WorldJournal) -> None:
        self._world = world

    async def world_stream(self, *, after: int = 0, limit: int = 64) -> dict[str, Any]:
        if after < 0:
            raise ValueError("after 必须是不小于 0 的整数")
        await self._world.initialize()
        page = await self._world.stream(after, limit)
        return {
            "after": page.after,
            "end": page.end,
            "has_more": page.has_more,
            "commits": [commit_dict(commit) for commit in page.commits],
        }

    async def world_commit(self, commit_id: str) -> dict[str, Any] | None:
        await self._world.initialize()
        commit = await self._world.commit(commit_id)
        return commit_dict(commit) if commit is not None else None

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
        await self._world.initialize()
        frontier = await self._world.head(frozenset({scope}))
        when = parse_event_time(occurred_at) if occurred_at else datetime.now(UTC)
        commit = await self._world.append_commit(
            commit_id=event_id,
            kind=kind,
            source=source,
            summary=summary,
            scopes=frozenset({scope}),
            based_on=frontier,
            data=data or {},
            occurred_at=when,
        )
        return commit_dict(commit)


WORLD_JOURNAL = InstanceKey[WorldJournal]("world.journal")
WORLD_OPS = InstanceKey[WorldOps]("world.ops")


def _register(context: CompositionContext) -> None:
    if not context.contains(WORLD_JOURNAL):
        context.provide(WORLD_JOURNAL, build_world(context.config))
    context.provide(WORLD_OPS, WorldOps(context.require(WORLD_JOURNAL)))


MODULE_SPEC = ModuleSpec(key=WORLD_JOURNAL, requires=(), register=_register)


def build_world(config: AuroraConfig) -> WorldJournal:
    """为异步启动阶段构造尚未初始化的唯一 WorldJournal。"""
    database_path = config.project_root / resolve_directory(config.get(STORAGE_CONFIG), "world") / "world.sqlite3"
    return SqlAlchemyWorldJournal(database_path)
