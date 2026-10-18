"""基于世界线的简化记忆：查询最近有活动 scope 的最近提交。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.contracts import MemoryScopeSnapshot, MemorySnapshot, ScopeCatalog, ScopeKind
from src.utils import get_logger
from src.utils.patterns import pattern_matches

if TYPE_CHECKING:
    from src.contracts.pkgs.world import WorldReader

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
        scope_include: tuple[str, ...] = (),
        scope_exclude: tuple[str, ...] = (),
        catalog: ScopeCatalog | None = None,
        include_run_scopes: bool = False,
    ) -> None:
        if window <= timedelta(0):
            raise ValueError("memory window must be positive")
        if commits_per_scope <= 0:
            raise ValueError("commits_per_scope must be positive")
        self._reader = reader
        self._window = window
        self._commits_per_scope = commits_per_scope
        self._scope_include = tuple(scope_include)
        self._scope_exclude = tuple(scope_exclude)
        self._catalog = catalog
        self._include_run_scopes = include_run_scopes
        for entry in (*self._scope_include, *self._scope_exclude):
            pattern_matches(entry, "")

    async def recall(
        self,
        *,
        now: datetime | None = None,
        scopes: frozenset[str] | None = None,
    ) -> MemorySnapshot:
        """返回最近窗口内每个活跃 scope 的最新提交（含完整 data 细节）。

        域注册表把 ``kind=run`` 的域标为引擎运转台账而不是 Bot 的世界，默认不进入记忆；
        未声明的域一律保留，避免因为缺一条声明就丢掉真实世界内容。
        """
        observed_at = (now or datetime.now(UTC)).astimezone(UTC)
        window_start = observed_at - self._window
        active = await self._reader.active_scopes(window_start)
        selected = active if scopes is None else tuple(scope for scope in active if scope in scopes)
        selected = self._filter_scopes(selected)
        selected = self._exclude_run_scopes(selected)
        _logger.debug("Memory recall 开始 active_scope_count={} selected_scope_count={}", len(active), len(selected))
        snapshots: list[MemoryScopeSnapshot] = []
        for scope in selected:
            frontier = await self._reader.head(frozenset({scope}))
            head = frontier.sequence(scope)
            after = max(0, head - self._commits_per_scope)
            recent = await self._reader.commits(scope, after, self._commits_per_scope)
            commits = tuple(commit for commit in recent if commit.occurred_at >= window_start)
            snapshots.append(MemoryScopeSnapshot(scope, head, commits))
        snapshot = MemorySnapshot(window_start, tuple(snapshots))
        _logger.debug("Memory recall 完成 scope_count={}", len(snapshot.scopes))
        return snapshot

    def _exclude_run_scopes(self, scopes: tuple[str, ...]) -> tuple[str, ...]:
        """按域注册表剔除运行台账域；未声明的域一律保留。"""
        if self._catalog is None or self._include_run_scopes:
            return scopes
        return tuple(scope for scope in scopes if self._catalog.classify(scope) is not ScopeKind.RUN)

    def _filter_scopes(self, scopes: tuple[str, ...]) -> tuple[str, ...]:
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
    decision: bool | None = None
    for entry in patterns:
        if pattern_matches(entry, scope):
            decision = not entry.startswith("!")
    return decision
