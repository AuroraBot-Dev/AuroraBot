"""SQLAlchemy 驱动的持久化 WorldJournal。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, insert, inspect, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from aurora_bot.contracts import (
    EnvironmentEvent,
    TreeActivity,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldStreamPage,
)
from aurora_bot.utils import get_logger, thaw_json
from aurora_bot.world.migration import STEPS, TARGET_VERSION
from aurora_bot.world.models import Base, SchemaMetaRow, WorldCommitBaseRow, WorldCommitRow, WorldCommitScopeRow

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from sqlalchemy import ColumnElement
    from sqlalchemy.engine import Connection, RowMapping

_MAX_BODY_PAGE = 256
_MAX_TREE_INDEX = 1000


class SqlAlchemyWorldJournal:
    """使用 SQLite 与 SQLAlchemy ORM 保存 Bot 的只追加世界提交。"""

    def __init__(self, database_path: Path, *, page_size: int = 64, now: Callable[[], datetime] | None = None) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.database_path = database_path
        self._engine: AsyncEngine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path}", connect_args={"timeout": 30}
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._page_size = page_size
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        async with self._lock:
            if getattr(self, "_initialized", False):
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            async with self._engine.begin() as connection:
                await connection.run_sync(self._create_or_migrate)
            self._initialized = True
            _logger.info("WorldJournal 已初始化 schema_version={}", TARGET_VERSION)

    @staticmethod
    def _create_or_migrate(connection: Connection) -> None:
        if not inspect(connection).has_table("schema_meta"):
            Base.metadata.create_all(connection)
            connection.execute(insert(SchemaMetaRow).values(singleton=1, version=TARGET_VERSION))
            return
        version = connection.execute(select(SchemaMetaRow.version).where(SchemaMetaRow.singleton == 1)).scalar_one()
        if version > TARGET_VERSION:
            raise RuntimeError(f"world schema version {version} is newer than supported {TARGET_VERSION}")
        for current in range(version, TARGET_VERSION):
            step = STEPS.get(current)
            if step is None:
                raise RuntimeError(f"missing world migration {current} -> {current + 1}")
            step(connection)
            connection.execute(update(SchemaMetaRow).where(SchemaMetaRow.singleton == 1).values(version=current + 1))

    async def close(self) -> None:
        await self._engine.dispose()
        self._initialized = False
        _logger.info("WorldJournal 已关闭")

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit:
        return await self.append_commit(
            commit_id=event.event_id,
            kind=f"environment.{event.kind}",
            source=event.source,
            summary=event.summary,
            scopes=frozenset({event.scope}),
            based_on=WorldFrontier(),
            data=event.data,
            occurred_at=event.occurred_at,
        )

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
    ) -> WorldCommit:
        return (
            await self.append_commits(
                (
                    WorldCommitInput(
                        commit_id,
                        kind,
                        source,
                        summary,
                        scopes,
                        based_on,
                        data,
                        occurred_at,
                    ),
                )
            )
        )[0]

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
        """原子追加一组提交，并在每个 scope 内连续分配 sequence。"""
        if not inputs:
            return ()
        identifiers = [item.commit_id for item in inputs]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("WorldCommitInput commit IDs must be unique in one batch")
        async with self._lock, self._sessions.begin() as session:
            next_sequences: dict[str, int] = {}
            appended: list[WorldCommitRow] = []
            last_recorded_at = await session.scalar(select(func.max(WorldCommitRow.recorded_at)))
            for item in inputs:
                statement = select(WorldCommitRow).where(WorldCommitRow.commit_id == item.commit_id)
                existing = await session.scalar(statement)
                if existing is not None:
                    (commit,) = await self._load_commits(session, (existing,))
                    if not _matches_input(commit, item):
                        raise ValueError(f"WorldCommit ID 已被不同内容使用：{item.commit_id}")
                    appended.append(existing)
                    continue
                sequences = await self._allocate_sequences(session, item.scopes, next_sequences)
                recorded_at = self._now()
                if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
                    raise ValueError("世界日志的时间来源必须包含时区")
                recorded_at = recorded_at.astimezone(UTC)
                recorded_at = max(recorded_at, _as_utc(last_recorded_at)) if last_recorded_at else recorded_at
                last_recorded_at = recorded_at
                occurred_at = item.occurred_at or recorded_at
                row = WorldCommitRow(
                    commit_id=item.commit_id,
                    kind=item.kind,
                    source=item.source,
                    summary=item.summary,
                    occurred_at=occurred_at,
                    recorded_at=recorded_at,
                    payload=thaw_json(item.data),
                )
                session.add(row)
                session.add_all(
                    WorldCommitScopeRow(commit_id=item.commit_id, scope=scope, sequence=sequence)
                    for scope, sequence in sequences.items()
                )
                session.add_all(
                    WorldCommitBaseRow(commit_id=item.commit_id, scope=scope, sequence=sequence)
                    for scope, sequence in item.based_on.positions.items()
                )
                appended.append(row)
            await session.flush()
            _logger.debug("世界提交已追加 commit_count={}", len(appended))
            return await self._load_commits(session, appended)

    @staticmethod
    async def _allocate_sequences(
        session: AsyncSession,
        scopes: frozenset[str],
        next_sequences: dict[str, int],
    ) -> dict[str, int]:
        sequences: dict[str, int] = {}
        for scope in sorted(scopes):
            next_sequence = next_sequences.get(scope)
            if next_sequence is None:
                maximum = await session.scalar(
                    select(func.max(WorldCommitScopeRow.sequence)).where(WorldCommitScopeRow.scope == scope)
                )
                next_sequence = int(maximum or 0) + 1
            sequences[scope] = next_sequence
            next_sequences[scope] = next_sequence + 1
        return sequences

    async def cursor(self) -> int:
        """返回世界线当前的全局 insertion cursor。"""
        async with self._sessions() as session:
            maximum = await session.scalar(select(func.max(WorldCommitRow.insertion_sequence)))
            return int(maximum or 0)

    async def active_scopes(self, since: datetime) -> tuple[str, ...]:
        """返回从 since 起有提交活动的 scope，按最近活动排序。"""
        since_utc = _as_utc(since).replace(tzinfo=None)
        async with self._sessions() as session:
            rows = await session.execute(
                select(
                    WorldCommitScopeRow.scope,
                    func.max(WorldCommitRow.insertion_sequence).label("last_insertion"),
                )
                .join(WorldCommitRow, WorldCommitRow.commit_id == WorldCommitScopeRow.commit_id)
                .where(WorldCommitRow.occurred_at >= since_utc)
                .group_by(WorldCommitScopeRow.scope)
                .order_by(func.max(WorldCommitRow.insertion_sequence).desc())
            )
        return tuple(str(row.scope) for row in rows)

    async def head(self, scopes: frozenset[str]) -> WorldFrontier:
        if not scopes:
            return WorldFrontier()
        async with self._sessions() as session:
            positions: dict[str, int] = {}
            for scope in scopes:
                maximum = await session.scalar(
                    select(func.max(WorldCommitScopeRow.sequence)).where(WorldCommitScopeRow.scope == scope)
                )
                positions[scope] = int(maximum or 0)
            return WorldFrontier(positions)

    async def commit(self, commit_id: str) -> WorldCommit | None:
        """按稳定 commit id 读取一次提交的完整正文；不存在时返回 None。"""
        if not commit_id.strip():
            raise ValueError("commit_id must not be empty")
        async with self._sessions() as session:
            row = await session.scalar(select(WorldCommitRow).where(WorldCommitRow.commit_id == commit_id))
            if row is None:
                return None
            return (await self._load_commits(session, (row,)))[0]

    async def commits(self, scope: str, after: int, limit: int) -> tuple[WorldCommit, ...]:
        """有界读取一个 scope 中序号大于 after 的提交正文，按写入顺序返回。"""
        if not scope.strip():
            raise ValueError("scope must not be empty")
        if after < 0:
            raise ValueError("after must not be negative")
        if limit < 1 or limit > _MAX_BODY_PAGE:
            raise ValueError(f"limit must be within 1..{_MAX_BODY_PAGE}")
        async with self._sessions() as session:
            statement = (
                select(WorldCommitRow)
                .join(WorldCommitScopeRow, WorldCommitScopeRow.commit_id == WorldCommitRow.commit_id)
                .where(WorldCommitScopeRow.scope == scope, WorldCommitScopeRow.sequence > after)
                .order_by(WorldCommitRow.insertion_sequence)
                .limit(limit)
            )
            rows = await session.scalars(statement)
            return await self._load_commits(session, list(rows))

    async def stream(self, after: int, limit: int) -> WorldStreamPage:
        """按全局 insertion cursor 读取连续事件流。"""
        if after < 0:
            raise ValueError("after must not be negative")
        if limit < 1 or limit > _MAX_BODY_PAGE:
            raise ValueError(f"limit must be within 1..{_MAX_BODY_PAGE}")
        async with self._sessions() as session:
            statement = (
                select(WorldCommitRow)
                .where(WorldCommitRow.insertion_sequence > after)
                .order_by(WorldCommitRow.insertion_sequence)
                .limit(limit + 1)
            )
            rows = list(await session.scalars(statement))
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            commits = await self._load_commits(session, page_rows)
            end = max((row.insertion_sequence for row in page_rows), default=after)
            return WorldStreamPage(after, end, commits, has_more)

    async def tree_index(self, limit: int) -> tuple[TreeActivity, ...]:
        """从引擎提交的 tree_id 事实推导 Bot 森林索引，按最近活动排序。"""
        if limit < 1 or limit > _MAX_TREE_INDEX:
            raise ValueError(f"limit must be within 1..{_MAX_TREE_INDEX}")
        async with self._sessions() as session:
            tree_id = func.json_extract(WorldCommitRow.payload, "$.tree_id")
            rows = await session.execute(
                select(
                    tree_id.label("tree_id"),
                    func.count().label("commit_count"),
                    func.min(WorldCommitRow.occurred_at).label("first_seen"),
                    func.max(WorldCommitRow.occurred_at).label("last_seen"),
                )
                .where(tree_id.is_not(None), tree_id != "")
                .group_by(tree_id)
                .order_by(func.max(WorldCommitRow.occurred_at).desc())
                .limit(limit)
            )
        return tuple(_tree_activity(row._mapping) for row in rows)

    async def delta(self, start: WorldFrontier, scopes: frozenset[str]) -> WorldDeltaPage:
        """按域分区读取前沿之后的一页提交；域过滤与排序全部由 SQLite 的索引完成。"""
        if not scopes:
            return WorldDeltaPage(start, start, (), False)
        ordered = sorted(scopes)
        async with self._sessions() as session:
            statement = (
                select(WorldCommitRow)
                .join(WorldCommitScopeRow, WorldCommitScopeRow.commit_id == WorldCommitRow.commit_id)
                .where(or_(*(_advances(scope, start.sequence(scope)) for scope in ordered)))
                .order_by(WorldCommitRow.insertion_sequence)
                .limit(self._page_size)
                .distinct()
            )
            commits = await self._load_commits(session, list(await session.scalars(statement)))
            end = start.advance(
                {
                    scope: max([*(commit.scopes.get(scope, 0) for commit in commits), start.sequence(scope)])
                    for scope in scopes
                }
            )
            more = len(commits) == self._page_size and await self._has_more(session, end, ordered)
            return WorldDeltaPage(start, end, commits, more)

    @staticmethod
    async def _has_more(session: AsyncSession, end: WorldFrontier, scopes: Sequence[str]) -> bool:
        """域分区上是否还有越过 end 的提交；只查分区索引，不载入正文。"""
        statement = (
            select(WorldCommitScopeRow.id)
            .where(or_(*(_advances(scope, end.sequence(scope)) for scope in scopes)))
            .limit(1)
        )
        return await session.scalar(statement) is not None

    async def _load_commits(self, session: AsyncSession, rows: Sequence[WorldCommitRow]) -> tuple[WorldCommit, ...]:
        """按页批量载入提交正文：分区序号与观察前沿各一次查询。"""
        if not rows:
            return ()
        identifiers = [row.commit_id for row in rows]
        scopes: dict[str, dict[str, int]] = {}
        based_on: dict[str, dict[str, int]] = {}
        scope_rows = await session.scalars(
            select(WorldCommitScopeRow).where(WorldCommitScopeRow.commit_id.in_(identifiers))
        )
        for item in scope_rows:
            scopes.setdefault(item.commit_id, {})[item.scope] = item.sequence
        base_rows = await session.scalars(
            select(WorldCommitBaseRow).where(WorldCommitBaseRow.commit_id.in_(identifiers))
        )
        for item in base_rows:
            based_on.setdefault(item.commit_id, {})[item.scope] = item.sequence
        return tuple(_as_commit(row, scopes.get(row.commit_id, {}), based_on.get(row.commit_id, {})) for row in rows)


def _advances(scope: str, sequence: int) -> ColumnElement[bool]:
    """域分区中一条越过给定序号的提交；由 `(scope, sequence)` 索引直接回答。"""
    return and_(WorldCommitScopeRow.scope == scope, WorldCommitScopeRow.sequence > sequence)


def _as_commit(row: WorldCommitRow, scopes: dict[str, int], based_on: dict[str, int]) -> WorldCommit:
    occurred_at = row.occurred_at.replace(tzinfo=UTC) if row.occurred_at.tzinfo is None else row.occurred_at
    return WorldCommit(
        row.commit_id,
        row.kind,
        row.source,
        row.summary,
        occurred_at,
        scopes,
        WorldFrontier(based_on),
        row.payload,
        cursor=row.insertion_sequence,
        recorded_at=_as_utc(row.recorded_at),
    )


def _matches_input(commit: WorldCommit, item: WorldCommitInput) -> bool:
    return (
        (commit.kind, commit.source, commit.summary) == (item.kind, item.source, item.summary)
        and set(commit.scopes) == set(item.scopes)
        and dict(commit.based_on.positions) == dict(item.based_on.positions)
        and dict(commit.data) == dict(item.data)
        and (item.occurred_at is None or commit.occurred_at == item.occurred_at)
    )


def _tree_activity(row: RowMapping) -> TreeActivity:
    tree_id = row["tree_id"]
    if not isinstance(tree_id, str):
        raise RuntimeError("世界提交的 tree_id 必须是字符串")
    return TreeActivity(tree_id, int(row["commit_count"]), _as_utc(row["first_seen"]), _as_utc(row["last_seen"]))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
