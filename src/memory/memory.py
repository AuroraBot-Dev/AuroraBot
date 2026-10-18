"""在确定的历史边界内，为 Bot 读取世界经历和主体状态。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.contracts import MemoryScopeSnapshot, MemorySnapshot, ScopeCatalog, ScopeKind
from src.contracts.memory import MemoryRequest
from src.memory.index import MemoryIndex
from src.utils import get_logger
from src.utils.patterns import pattern_matches

if TYPE_CHECKING:
    from src.contracts.pkgs.bot import BotStateStore
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
        window: timedelta = DEFAULT_MEMORY_WINDOW,
        commits_per_scope: int = DEFAULT_COMMITS_PER_SCOPE,
        scope_include: tuple[str, ...] = (),
        scope_exclude: tuple[str, ...] = (),
        catalog: ScopeCatalog | None = None,
        include_run_scopes: bool = False,
        state: BotStateStore | None = None,
    ) -> None:
        if window <= timedelta(0):
            raise ValueError("memory window must be positive")
        if commits_per_scope <= 0:
            raise ValueError("commits_per_scope must be positive")
        self._reader = reader
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
        recent = tuple(commit for commit in history.commits if commit.occurred_at >= window_start)
        latest: dict[str, datetime] = {}
        for commit in recent:
            for scope in commit.scopes:
                latest[scope] = max(latest.get(scope, commit.occurred_at), commit.occurred_at)
        active = tuple(sorted(latest, key=lambda scope: (-latest[scope].timestamp(), scope)))
        selected = active if request.scopes is None else tuple(scope for scope in active if scope in request.scopes)
        selected = self._filter_scopes(selected)
        selected = self._exclude_run_scopes(selected)
        _logger.debug("Memory recall 开始 active_scope_count={} selected_scope_count={}", len(active), len(selected))
        snapshots: list[MemoryScopeSnapshot] = []
        for scope in selected:
            commits = tuple(commit for commit in recent if scope in commit.scopes)[-self._commits_per_scope :]
            scope_head = max(commit.scopes[scope] for commit in history.commits if scope in commit.scopes)
            snapshots.append(MemoryScopeSnapshot(scope, scope_head, commits))
        continuity = await self._state.snapshot_at(history.cursor) if self._state is not None else None
        snapshot = MemorySnapshot(window_start, tuple(snapshots), continuity, history.cursor, observed_at)
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
