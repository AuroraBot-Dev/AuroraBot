"""Bot 世界提交与观察前沿的值对象；事件由提交方生产并确定所属域。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from aurora_bot.contracts.data import freeze_object

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from aurora_bot.contracts.memory import MemoryBundle, MemoryContinuity, MemoryRecall

MCP_EVENT_RECEIVED = "mcp.event.received"


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
        """冻结事件内容，调用方持有的嵌套容器不再影响已提交输入。"""
        fields = (self.event_id, self.source, self.scope, self.kind, self.summary)
        if not all(field.strip() for field in fields):
            raise ValueError("EnvironmentEvent requires non-empty identity and summary fields")
        object.__setattr__(self, "data", freeze_object(self.data))
        object.__setattr__(self, "occurred_at", _utc_time(self.occurred_at))


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
    cursor: int = 0
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        """提交元数据和任意深度的 JSON 内容都保持不可变。"""
        if not all((self.commit_id.strip(), self.kind.strip(), self.source.strip(), self.summary.strip())):
            raise ValueError("WorldCommit requires non-empty identity and summary fields")
        scopes = dict(self.scopes)
        if not scopes or any(not scope.strip() or sequence <= 0 for scope, sequence in scopes.items()):
            raise ValueError("WorldCommit requires positive sequences for non-empty scopes")
        object.__setattr__(self, "scopes", MappingProxyType(scopes))
        object.__setattr__(self, "data", freeze_object(self.data))
        object.__setattr__(self, "occurred_at", _utc_time(self.occurred_at))
        if self.cursor < 0:
            raise ValueError("世界提交的全局游标不能小于零")
        if self.recorded_at is not None:
            object.__setattr__(self, "recorded_at", _utc_time(self.recorded_at))


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
        """写入前复制完整内容，重试身份不会被外部容器修改。"""
        if not all((self.commit_id.strip(), self.kind.strip(), self.source.strip(), self.summary.strip())):
            raise ValueError("WorldCommitInput requires non-empty identity and summary fields")
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        if not self.scopes or any(not scope.strip() for scope in self.scopes):
            raise ValueError("WorldCommitInput requires non-empty scopes")
        object.__setattr__(self, "data", freeze_object(self.data))
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", _utc_time(self.occurred_at))


def _utc_time(value: datetime) -> datetime:
    """记录实际瞬间，持久化与排序不依赖运行机器的本地时区。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("世界时间必须包含时区")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class WorldDeltaPage:
    """从某个 frontier 起的一页已披露提交索引。"""

    start: WorldFrontier
    end: WorldFrontier
    commits: tuple[WorldCommit, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class MemoryScopeSnapshot:
    """记忆查询中一个已选中的域及其可见来源。"""

    scope: str
    head: int
    commits: tuple[WorldCommit, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "commits", tuple(self.commits))
        if not self.scope.strip() or self.head < 0:
            raise ValueError("MemoryScopeSnapshot requires a non-empty scope and non-negative head")


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """同一获知截点上的连续性状态、来源和推荐集合。"""

    window_start: datetime
    scopes: tuple[MemoryScopeSnapshot, ...]
    continuity: MemoryContinuity | None = None
    bundles: tuple[MemoryBundle, ...] | None = None
    required: tuple[WorldCommit, ...] = ()
    missing_refs: tuple[str, ...] = ()
    recall: MemoryRecall | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", tuple(self.scopes))


@dataclass(frozen=True, slots=True)
class WorldStreamPage:
    """按全局 insertion cursor 读取的一页连续事件流。"""

    after: int
    end: int
    commits: tuple[WorldCommit, ...]
    has_more: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "commits", tuple(self.commits))
        if self.after < 0 or self.end < self.after:
            raise ValueError("WorldStreamPage requires 0 <= after <= end")


@dataclass(frozen=True, slots=True)
class RunActivity:
    run_id: str
    commit_count: int
    first_seen: datetime
    last_seen: datetime

    def __post_init__(self) -> None:
        if not self.run_id.strip() or self.commit_count <= 0:
            raise ValueError("RunActivity requires a non-empty run id and positive commit count")
        if self.first_seen > self.last_seen:
            raise ValueError("RunActivity first_seen must not be after last_seen")


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
