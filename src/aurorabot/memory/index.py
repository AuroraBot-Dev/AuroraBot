"""从追加式世界流恢复的记忆索引，历史读取不会改变实时投影。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from aurorabot.contracts.pkgs.world import WorldReader
    from aurorabot.contracts.world import WorldCommit


@dataclass(frozen=True, slots=True)
class VisibleHistory:
    """同一获知截点上的经历和可用于恢复主体的游标。"""

    cursor: int
    commits: tuple[WorldCommit, ...]


class MemoryIndex:
    """保留可重建的经历索引，所有候选受游标和获知时间双重限制。"""

    def __init__(self, reader: WorldReader) -> None:
        """绑定世界读取端口，不另行持有事实权威。"""
        self._reader = reader
        self._cursor = 0
        self._commits: list[WorldCommit] = []
        self._lock = asyncio.Lock()

    async def visible(self, cursor: int, observed_at: datetime) -> VisibleHistory:
        """先同步确定的世界前缀，再排除未来发生或未来获知的经历。"""
        async with self._lock:
            await self._sync(cursor)
            visible: list[WorldCommit] = []
            known_cursor = 0
            for commit in self._commits:
                if commit.cursor > cursor:
                    break
                if commit.recorded_at is None:
                    raise ValueError("世界读取端口必须提供提交的获知时间")
                if commit.recorded_at > observed_at:
                    break
                known_cursor = commit.cursor
                if commit.occurred_at <= observed_at:
                    visible.append(commit)
            return VisibleHistory(known_cursor, tuple(visible))

    async def _sync(self, cursor: int) -> None:
        """只推进索引；重启后可按相同顺序重新投影。"""
        while self._cursor < cursor:
            page = await self._reader.stream(self._cursor, 256)
            if not page.commits:
                raise ValueError("世界流未能提供已声明的记忆游标")
            for commit in page.commits:
                if commit.cursor > cursor:
                    self._cursor = cursor
                    return
                if commit.cursor <= self._cursor:
                    raise ValueError("记忆索引要求世界提交携带递增全局游标")
                self._commits.append(commit)
                self._cursor = commit.cursor
