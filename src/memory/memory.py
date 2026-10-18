"""在确定的历史边界内，为 Bot 读取世界经历和主体状态。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.contracts import MemoryScopeSnapshot, MemorySnapshot, ScopeCatalog, ScopeKind
from src.contracts.memory import MemoryRequest
from src.memory.continuity import select_continuity
from src.memory.index import MemoryIndex
from src.memory.selection import select_memories
from src.utils import get_logger
from src.utils.patterns import pattern_matches

if TYPE_CHECKING:
    from src.contracts.pkgs.bot import BotStateStore
    from src.contracts.pkgs.memory import MemoryPolicy
    from src.contracts.pkgs.world import WorldReader

_logger = get_logger(__name__)

DEFAULT_MEMORY_WINDOW = timedelta(hours=1)
DEFAULT_COMMITS_PER_SCOPE = 50


class Memory:
    """只读世界消费者；经历和主体恢复状态共享同一可见截点。"""

    def __init__(
        self,
        reader: WorldReader,
        *,
        policy: MemoryPolicy,
        window: timedelta = DEFAULT_MEMORY_WINDOW,
        commits_per_scope: int = DEFAULT_COMMITS_PER_SCOPE,
        scope_include: tuple[str, ...] = (),
        scope_exclude: tuple[str, ...] = (),
        catalog: ScopeCatalog | None = None,
        include_run_scopes: bool = False,
        state: BotStateStore | None = None,
    ) -> None:
        """绑定经历来源与排序策略，读取范围和主体状态各自显式注入。"""
        if window <= timedelta(0):
            raise ValueError("memory window must be positive")
        if commits_per_scope <= 0:
            raise ValueError("commits_per_scope must be positive")
        self._reader = reader
        self._policy = policy
        self._index = MemoryIndex(reader)
        self._window = window
        self._commits_per_scope = commits_per_scope
        self._scope_include = tuple(scope_include)
        self._scope_exclude = tuple(scope_exclude)
        self._catalog = catalog
        self._include_run_scopes = include_run_scopes
        self._state = state
        for entry in (*self._scope_include, *self._scope_exclude):
            pattern_matches(entry, "")

    async def recall(self, request: MemoryRequest | None = None) -> MemorySnapshot:
        """冻结世界前缀，迟到事实和后续反馈均不会进入过去的读取。"""
        request = request or MemoryRequest()
        head = await self._reader.cursor()
        cursor = head if request.cursor is None else request.cursor
        if cursor > head:
            raise ValueError("记忆读取游标超出当前世界")
        observed_at = (request.observed_at or datetime.now(UTC)).astimezone(UTC)
        window_start = observed_at - self._window
        history = await self._index.visible(cursor, observed_at)
        all_scopes = tuple(sorted({scope for commit in history.commits for scope in commit.scopes}))
        selected = self._exclude_run_scopes(self._filter_scopes(all_scopes))
        if request.scopes is not None:
            selected = tuple(scope for scope in selected if scope in request.scopes)
        eligible = tuple(commit for commit in history.commits if set(commit.scopes).intersection(selected))
        recent_by_id = {}
        for scope in selected:
            recent = tuple(
                commit for commit in eligible if scope in commit.scopes and commit.occurred_at >= window_start
            )
            recent_by_id.update((commit.commit_id, commit) for commit in recent[-self._commits_per_scope :])
        continuity = (
            select_continuity(await self._state.snapshot_at(history.cursor), request)
            if self._state is not None
            else None
        )
        normalized = replace(request, cursor=history.cursor, observed_at=observed_at)
        if not normalized.focus_goal_ids and continuity is not None:
            normalized = replace(normalized, focus_goal_ids=tuple(goal.goal_id for goal in continuity.goals))
        selection = await asyncio.to_thread(
            select_memories, eligible, tuple(recent_by_id.values()), normalized, continuity, self._policy
        )
        chosen = {commit.commit_id: commit for commit in selection.required}
        for bundle in selection.bundles:
            chosen.update((commit.commit_id, commit) for commit in bundle.commits)
        recent = tuple(sorted(chosen.values(), key=lambda commit: commit.cursor))
        latest: dict[str, datetime] = {}
        for commit in recent:
            for scope in commit.scopes:
                latest[scope] = max(latest.get(scope, commit.occurred_at), commit.occurred_at)
        selected = tuple(
            sorted((scope for scope in selected if scope in latest), key=lambda s: (-latest[s].timestamp(), s))
        )
        snapshots: list[MemoryScopeSnapshot] = []
        for scope in selected:
            commits = tuple(commit for commit in recent if scope in commit.scopes)
            scope_head = max(commit.scopes[scope] for commit in history.commits if scope in commit.scopes)
            snapshots.append(MemoryScopeSnapshot(scope, scope_head, commits))
        snapshot = MemorySnapshot(
            window_start,
            tuple(snapshots),
            continuity,
            history.cursor,
            observed_at,
            selection.bundles,
            selection.required,
            selection.missing_refs,
            self._policy.ref,
        )
        _logger.debug("Memory recall 完成 scope_count={}", len(snapshot.scopes))
        return snapshot

    def _exclude_run_scopes(self, scopes: tuple[str, ...]) -> tuple[str, ...]:
        """按域注册表剔除运行台账域；未声明的域一律保留。"""
        if self._catalog is None or self._include_run_scopes:
            return scopes
        return tuple(scope for scope in scopes if self._catalog.classify(scope) is not ScopeKind.RUN)

    def _filter_scopes(self, scopes: tuple[str, ...]) -> tuple[str, ...]:
        """依配置依次应用域包含规则和排除规则。"""
        if not self._scope_include and not self._scope_exclude:
            return scopes
        kept: list[str] = []
        for scope in scopes:
            if self._scope_include and _last_match(self._scope_include, scope) is not True:
                continue
            if self._scope_exclude and _last_match(self._scope_exclude, scope) is True:
                continue
            kept.append(scope)
        return tuple(kept)


def _last_match(patterns: tuple[str, ...], scope: str) -> bool | None:
    """采用最后一条匹配规则，允许显式取消先前选择。"""
    decision: bool | None = None
    for entry in patterns:
        if pattern_matches(entry, scope):
            decision = not entry.startswith("!")
    return decision
