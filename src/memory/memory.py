"""基于世界线的简化记忆：查询最近有活动 scope 的最近提交。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from src.contracts import MemoryScopeSnapshot, MemorySnapshot, WorldReader
from src.utils import get_logger

_logger = get_logger(__name__)

DEFAULT_MEMORY_WINDOW = timedelta(hours=1)
DEFAULT_COMMITS_PER_SCOPE = 50


class Memory:
    """只读世界消费者；把近期活动组织为可注入 system 的记忆快照。"""

    def __init__(
        self,
        reader: WorldReader,
        *,
        window: timedelta = DEFAULT_MEMORY_WINDOW,
        commits_per_scope: int = DEFAULT_COMMITS_PER_SCOPE,
    ) -> None:
        if window <= timedelta(0):
            raise ValueError("memory window must be positive")
        if commits_per_scope <= 0:
            raise ValueError("commits_per_scope must be positive")
        self._reader = reader
        self._window = window
        self._commits_per_scope = commits_per_scope

    async def recall(
        self,
        *,
        now: datetime | None = None,
        scopes: frozenset[str] | None = None,
    ) -> MemorySnapshot:
        """返回最近窗口内每个活跃 scope 的最新提交（含完整 data 细节）。"""
        observed_at = (now or datetime.now(UTC)).astimezone(UTC)
        window_start = observed_at - self._window
        active = await self._reader.active_scopes(window_start)
        selected = active if scopes is None else tuple(scope for scope in active if scope in scopes)
        _logger.debug("Memory recall 开始 active_scope_count=%d selected_scope_count=%d", len(active), len(selected))
        snapshots: list[MemoryScopeSnapshot] = []
        for scope in selected:
            frontier = await self._reader.head(frozenset({scope}))
            head = frontier.sequence(scope)
            after = max(0, head - self._commits_per_scope)
            recent = await self._reader.commits(scope, after, self._commits_per_scope)
            commits = tuple(commit for commit in recent if commit.occurred_at >= window_start)
            snapshots.append(MemoryScopeSnapshot(scope, head, commits))
        snapshot = MemorySnapshot(window_start, tuple(snapshots))
        _logger.debug("Memory recall 完成 scope_count=%d", len(snapshot.scopes))
        return snapshot

    @staticmethod
    def render(snapshot: MemorySnapshot) -> str:
        """把记忆快照渲染为 PromptAssembler 的 system 片段。"""
        lines = ["## 最近一小时的世界活动"]
        lines.append(f"窗口起点：{snapshot.window_start.isoformat()}")
        for scope in snapshot.scopes:
            lines.append(f"### scope：{scope.scope}（head={scope.head}）")
            for commit in scope.commits:
                lines.append(f"- {commit.occurred_at.isoformat()} [{commit.kind}] {commit.summary}")
                if commit.data:
                    lines.append(f"  数据：{_compact_json(dict(commit.data))}")
        return "\n".join(lines)


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
