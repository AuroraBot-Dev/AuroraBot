"""``world`` 暴露的全局端口：世界线的只读、只写与持久化契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from aurora_bot.contracts.world import (
        EnvironmentEvent,
        TreeActivity,
        WorldCommit,
        WorldCommitInput,
        WorldDeltaPage,
        WorldFrontier,
        WorldStreamPage,
    )


class WorldReader(Protocol):
    """世界线的只读端口；供 prompt、memory、cadence 等消费者使用。"""

    async def cursor(self) -> int: ...

    async def head(self, scopes: frozenset[str]) -> WorldFrontier: ...

    async def delta(self, start: WorldFrontier, scopes: frozenset[str]) -> WorldDeltaPage: ...

    async def active_scopes(self, since: datetime) -> tuple[str, ...]: ...

    async def commit(self, commit_id: str) -> WorldCommit | None: ...

    async def commits(self, scope: str, after: int, limit: int) -> tuple[WorldCommit, ...]: ...

    async def stream(self, after: int, limit: int) -> WorldStreamPage: ...

    async def tree_index(self, limit: int) -> tuple[TreeActivity, ...]: ...


class WorldWriter(Protocol):
    """世界线的只写端口；供 console、mcp、cadence 等生产者使用。"""

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit: ...

    async def append_commit(
        self,
        *,
        commit_id: str,
        kind: str,
        source: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, Any],
        occurred_at: datetime | None = None,
    ) -> WorldCommit: ...

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]: ...


class WorldJournal(WorldReader, WorldWriter, Protocol):
    """世界事实与效果因果的唯一持久化端口。"""

    async def initialize(self) -> None: ...

    async def close(self) -> None: ...
