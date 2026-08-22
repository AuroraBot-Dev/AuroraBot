"""Bot 世界提交、观察前沿与存储端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class WorldFrontier:
    """已观察的 scope → 单调提交序号。"""

    positions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        positions = dict(self.positions)
        if any(not scope.strip() or sequence < 0 for scope, sequence in positions.items()):
            raise ValueError("WorldFrontier contains an invalid scope or sequence")
        object.__setattr__(self, "positions", MappingProxyType(positions))

    def sequence(self, scope: str) -> int:
        return self.positions.get(scope, 0)

    def advance(self, positions: Mapping[str, int]) -> WorldFrontier:
        merged = dict(self.positions)
        for scope, sequence in positions.items():
            if sequence < merged.get(scope, 0):
                raise ValueError("WorldFrontier cannot move backwards")
            merged[scope] = sequence
        return WorldFrontier(merged)


@dataclass(frozen=True, slots=True)
class EnvironmentEvent:
    """由环境提交给 Bot 的稳定事实。"""

    event_id: str
    source: str
    scope: str
    kind: str
    occurred_at: datetime
    summary: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fields = (self.event_id, self.source, self.scope, self.kind, self.summary)
        if not all(field.strip() for field in fields):
            raise ValueError("EnvironmentEvent requires non-empty identity and summary fields")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class WorldCommit:
    """只追加世界日志中的一次提交。"""

    commit_id: str
    kind: str
    source: str
    summary: str
    occurred_at: datetime
    scopes: Mapping[str, int]
    based_on: WorldFrontier
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all((self.commit_id.strip(), self.kind.strip(), self.source.strip(), self.summary.strip())):
            raise ValueError("WorldCommit requires non-empty identity and summary fields")
        scopes = dict(self.scopes)
        if not scopes or any(not scope.strip() or sequence <= 0 for scope, sequence in scopes.items()):
            raise ValueError("WorldCommit requires positive sequences for non-empty scopes")
        object.__setattr__(self, "scopes", MappingProxyType(scopes))
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class WorldCommitInput:
    """写入世界日志前的提交请求；由 journal 原子分配 scope sequence。"""

    commit_id: str
    kind: str
    source: str
    summary: str
    scopes: frozenset[str]
    based_on: WorldFrontier
    data: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all((self.commit_id.strip(), self.kind.strip(), self.source.strip(), self.summary.strip())):
            raise ValueError("WorldCommitInput requires non-empty identity and summary fields")
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        if not self.scopes or any(not scope.strip() for scope in self.scopes):
            raise ValueError("WorldCommitInput requires non-empty scopes")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class WorldDeltaPage:
    """从某个 frontier 起的一页已披露提交索引。"""

    start: WorldFrontier
    end: WorldFrontier
    commits: tuple[WorldCommit, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class TreeActivity:
    """由世界日志推导出的一棵树的活动摘要。"""

    tree_id: str
    commit_count: int
    first_seen: datetime
    last_seen: datetime

    def __post_init__(self) -> None:
        if not self.tree_id.strip() or self.commit_count <= 0:
            raise ValueError("TreeActivity requires a non-empty tree id and positive commit count")
        if self.first_seen > self.last_seen:
            raise ValueError("TreeActivity first_seen must not be after last_seen")


@dataclass(frozen=True, slots=True)
class ToolScopes:
    """工具调用需要观察及发布的额外世界域。"""

    observe: frozenset[str] = frozenset()
    publish: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "observe", frozenset(self.observe))
        object.__setattr__(self, "publish", frozenset(self.publish))
        if any(not scope.strip() for scope in (*self.observe, *self.publish)):
            raise ValueError("ToolScopes must not contain empty scopes")


class WorldJournal(Protocol):
    """世界事实与效果因果的唯一持久化端口。"""

    async def initialize(self) -> None: ...

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit: ...

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]: ...

    async def head(self, scopes: frozenset[str]) -> WorldFrontier: ...

    async def delta(self, start: WorldFrontier, scopes: frozenset[str]) -> WorldDeltaPage: ...

    async def commit(self, commit_id: str) -> WorldCommit | None: ...

    async def commits(self, scope: str, after: int, limit: int) -> tuple[WorldCommit, ...]: ...

    async def tree_index(self, limit: int) -> tuple[TreeActivity, ...]: ...

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
