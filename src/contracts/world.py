"""Bot 世界提交、观察前沿与存储端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

# 稳定的世界 scope 与事件 kind 常量；scope 的实际归属由提交方决定，
# world 只负责校验、编号与追加。
SYSTEM_SCOPE = "aurora:system"
CONFIG_SCOPE = "aurora:config"
CONSOLE_SCOPE = "aurora:console"

TREE_STARTED = "engine.tree.started"
TREE_COMPLETED = "engine.tree.completed"
TREE_FAILED = "engine.tree.failed"
NODE_SPAWNED = "engine.node.spawned"
NODE_COMPLETED = "engine.node.completed"
NODE_FAILED = "engine.node.failed"
MODEL_REQUESTED = "engine.model.requested"
MODEL_COMPLETED = "engine.model.completed"
MODEL_FAILED = "engine.model.failed"
TOOL_REQUESTED = "tool.requested"
TOOL_SUCCEEDED = "tool.succeeded"
TOOL_FAILED = "tool.failed"
TOOL_UNKNOWN = "tool.unknown"
OUTPUT_REQUESTED = "output.requested"
OUTPUT_COMMITTED = "output.committed"
WORLD_DELTA_DELIVERED = "engine.world.delta_delivered"
CONSOLE_INPUT = "console.input"
MCP_APP_STARTING = "mcp.app.starting"
MCP_APP_READY = "mcp.app.ready"
MCP_APP_FAILED = "mcp.app.failed"
MCP_APP_DISCONNECTED = "mcp.app.disconnected"
MCP_CATALOG_FROZEN = "mcp.catalog.frozen"
MCP_CATALOG_CHANGED = "mcp.catalog.changed"
MCP_EVENT_RECEIVED = "mcp.event.received"


def tree_scope(tree_id: str) -> str:
    """返回一次 AgentTree 运行的标准世界 scope。"""
    if not tree_id.strip():
        raise ValueError("tree_id must not be empty")
    return f"aurora:tree:{tree_id}"


def mcp_scope(package: str) -> str:
    """返回一个 MCP App 的标准世界 scope。"""
    if not package.strip():
        raise ValueError("package must not be empty")
    return f"aurora:mcp:{package}"


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
class MemoryScopeSnapshot:
    """记忆查询中一个有近期活动的 scope 及其最近提交。"""

    scope: str
    head: int
    commits: tuple[WorldCommit, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "commits", tuple(self.commits))
        if not self.scope.strip() or self.head < 0:
            raise ValueError("MemoryScopeSnapshot requires a non-empty scope and non-negative head")


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """按活跃 scope 分组的世界记忆快照。"""

    window_start: datetime
    scopes: tuple[MemoryScopeSnapshot, ...]

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


class MemoryReader(Protocol):
    """按活跃 scope 提供世界记忆快照的只读端口。"""

    async def recall(
        self,
        *,
        now: datetime | None = None,
        scopes: frozenset[str] | None = None,
    ) -> MemorySnapshot: ...


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
