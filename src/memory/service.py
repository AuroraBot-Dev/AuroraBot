"""记忆引擎（RFC 0216）：短期窗口 + LLM 概要，长期 durable_facts（mem0 可选）。

分层（RFC 0217 起使用 SQLAlchemy ORM，物理 Schema 不变）：
- ``memory_messages``：最近 N 条原始消息（窗口）；
- ``session_memory``：窗口外压缩概要（LLM 生成，fast role）；
- ``durable_facts``：长期事实（mem0 不可用时降级的关键词检索）。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy import Index, Integer, String, UniqueConstraint, create_engine, delete, desc, event, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy.engine import CursorResult, Engine

from src.contracts import (
    MemoryContextSnapshot,
    MemoryEntry,
    MemoryMessage,
    MemoryQuery,
)
from src.utils import get_logger
from src.utils.migration import migrate_to


class _Summarizer(Protocol):
    """概要生成所需的网关窄面（避免 memory 依赖 ai 包，RFC 0200 边界）。"""

    async def get_response(self, role: str, inputs: list[dict]) -> dict[str, Any]: ...


logger = get_logger("aurora.memory.service")
_SUMMARY_LIMIT = 2400
_DEFAULT_WINDOW_MIN = 100
_DEFAULT_WINDOW_MAX = 300


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    ELLIPSIS = "…"
    SUMMARIZE_PROMPT = (
        "你负责记忆浓缩：把『最早记忆项』与一批旧对话再次压缩为一条更浓缩的"
        "记忆项（保留关键事实，丢弃已失去时效的细节）。\n"
        "最早记忆项：\n{summary}\n\n旧对话：\n{messages}\n\n只输出新的记忆项文本。"
    )


class _Base(DeclarativeBase):
    """memory.sqlite3 的声明式基类。"""


class MemoryReceiptRow(_Base):
    """memory_receipts：终态投影幂等回执。"""

    __tablename__ = "memory_receipts"

    task_id: Mapped[str] = mapped_column("task_id", String, primary_key=True)
    scope: Mapped[str] = mapped_column("scope", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)


class SessionMemoryRow(_Base):
    """session_memory：窗口外压缩概要（每 scope 一条）。"""

    __tablename__ = "session_memory"

    scope: Mapped[str] = mapped_column("scope", String, primary_key=True)
    summary: Mapped[str] = mapped_column("summary", String, nullable=False)
    updated_at: Mapped[str] = mapped_column("updated_at", String, nullable=False)


class DurableFactRow(_Base):
    """durable_facts：长期事实（UNIQUE(scope, content) 保证去重）。"""

    __tablename__ = "durable_facts"
    __table_args__ = (
        UniqueConstraint("scope", "content"),
        Index("idx_durable_facts_scope_created", "scope", desc("created_at")),
    )

    fact_id: Mapped[int] = mapped_column("fact_id", Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column("scope", String, nullable=False)
    content: Mapped[str] = mapped_column("content", String, nullable=False)
    source_task_id: Mapped[str] = mapped_column("source_task_id", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)


class MemoryMessageRow(_Base):
    """memory_messages：最近 N 条原始消息（窗口）。"""

    __tablename__ = "memory_messages"
    __table_args__ = (
        Index("idx_memory_messages_scope", "scope", "seq"),
        {"sqlite_autoincrement": True},
    )

    seq: Mapped[int] = mapped_column("seq", Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column("scope", String, nullable=False)
    role: Mapped[str] = mapped_column("role", String, nullable=False)
    content: Mapped[str] = mapped_column("content", String, nullable=False)
    at: Mapped[str] = mapped_column("at", String, nullable=False)


class MemoryService:
    """短期记忆（窗口+概要）+ 长期事实（可选 mem0）的组合实现。"""

    def __init__(
        self,
        memory_dir: "Path | None" = None,
        *,
        gateway: _Summarizer | None = None,
        window_min: int = _DEFAULT_WINDOW_MIN,
        window_max: int = _DEFAULT_WINDOW_MAX,
    ) -> None:
        self._memory_dir = memory_dir
        self._gateway: _Summarizer | None = gateway
        self._window_min = window_min
        self._window_max = window_max
        self._engine: Engine | None = None
        if memory_dir is not None:
            memory_dir.mkdir(parents=True, exist_ok=True)
            self._engine = _build_engine(memory_dir / "memory.sqlite3")
            self._initialize()
        from src.memory.long_term import LongTermMemory

        self._long_term = LongTermMemory(memory_dir) if memory_dir is not None else None

    def _initialize(self) -> None:
        """WAL 配置 + 按版本序列迁移到 TARGET_VERSION（utils.migration 框架）。"""
        from src.memory import migration

        assert self._engine is not None
        with self._engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))
            connection.execute(text("PRAGMA journal_size_limit=524288"))
            current = connection.exec_driver_sql("PRAGMA user_version").scalar() or 0
            migrate_to(
                connection,
                current=current,
                target=migration.TARGET_VERSION,
                steps=migration.STEPS,
                set_version=lambda c, version: c.exec_driver_sql(f"PRAGMA user_version = {version}"),
            )

    def history(self, *, scope: str | None = None, limit: int = 32) -> dict[str, Any]:
        """只读记忆历史（RFC 0218 观察）：窗口消息 + 概要 + 长期事实。"""
        if self._engine is None:
            return {"scope": scope, "window": [], "summaries": [], "facts": []}
        with self._session() as session:
            window_query = select(MemoryMessageRow).order_by(MemoryMessageRow.seq.desc()).limit(limit)
            if scope is not None:
                window_query = window_query.where(MemoryMessageRow.scope == scope)
            messages = session.execute(window_query).scalars().all()
            summary_query = select(SessionMemoryRow).order_by(SessionMemoryRow.updated_at.desc())
            if scope is not None:
                summary_query = summary_query.where(SessionMemoryRow.scope == scope)
            summaries = session.execute(summary_query).scalars().all()
            facts_query = select(DurableFactRow).order_by(DurableFactRow.created_at.desc()).limit(limit)
            if scope is not None:
                facts_query = facts_query.where(DurableFactRow.scope.in_((scope, "global")))
            facts = session.execute(facts_query).scalars().all()
        return {
            "scope": scope,
            "window": [
                {"scope": row.scope, "role": row.role, "content": row.content, "at": row.at}
                for row in reversed(messages)
            ],
            "summaries": [
                {"scope": row.scope, "summary": row.summary, "updated_at": row.updated_at} for row in summaries
            ],
            "facts": [
                {
                    "scope": row.scope,
                    "content": row.content,
                    "source_task_id": row.source_task_id,
                    "created_at": row.created_at,
                }
                for row in facts
            ],
        }

    def search(self, query: str, *, scope: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        """只读记忆检索（RFC 0218 观察）：对窗口消息与长期事实做词项匹配。"""
        if self._engine is None or not query.strip():
            return []
        terms = {term.casefold() for term in query.split() if len(term) > 1}
        if not terms:
            return []
        with self._session() as session:
            message_rows = session.execute(select(MemoryMessageRow)).scalars().all()
            fact_rows = session.execute(select(DurableFactRow)).scalars().all()
        candidates: list[dict[str, Any]] = []
        for row in message_rows:
            if scope is not None and row.scope != scope:
                continue
            hits = sum(term in row.content.casefold() for term in terms)
            if hits:
                candidates.append(
                    {
                        "kind": "window",
                        "scope": row.scope,
                        "content": row.content,
                        "role": row.role,
                        "at": row.at,
                        "hits": hits,
                    }
                )
        for row in fact_rows:
            if scope is not None and row.scope not in {scope, "global"}:
                continue
            hits = sum(term in row.content.casefold() for term in terms)
            if hits:
                candidates.append(
                    {
                        "kind": "fact",
                        "scope": row.scope,
                        "content": row.content,
                        "source_task_id": row.source_task_id,
                        "created_at": row.created_at,
                        "hits": hits,
                    }
                )
        candidates.sort(key=lambda item: item["hits"], reverse=True)
        return candidates[:limit]

    def status(self) -> dict[str, Any]:
        """只读记忆统计（RFC 0218 观察）：窗口/概要/长期计数。"""
        if self._engine is None:
            return {"enabled": False, "window_messages": 0, "summaries": 0, "facts": 0, "scopes": []}
        with self._session() as session:
            window_messages = session.scalar(select(func.count()).select_from(MemoryMessageRow)) or 0
            summaries = session.scalar(select(func.count()).select_from(SessionMemoryRow)) or 0
            facts = session.scalar(select(func.count()).select_from(DurableFactRow)) or 0
            scope_statement = select(MemoryMessageRow.scope).distinct().order_by(MemoryMessageRow.scope)
            scopes = session.execute(scope_statement).scalars().all()
        return {
            "enabled": True,
            "window_messages": window_messages,
            "summaries": summaries,
            "facts": facts,
            "scopes": [str(value) for value in scopes],
        }

    def recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
        if self._engine is None:
            return MemoryContextSnapshot()
        try:
            with self._session() as session:
                row = session.scalar(select(SessionMemoryRow.summary).where(SessionMemoryRow.scope == query.scope))
                summary = str(row) if row is not None else ""
                rows = session.execute(
                    select(MemoryMessageRow.role, MemoryMessageRow.content, MemoryMessageRow.at)
                    .where(MemoryMessageRow.scope == query.scope)
                    .order_by(MemoryMessageRow.seq.desc())
                    .limit(self._window_max)
                ).all()
                window = tuple(MemoryMessage(str(role), str(content), str(at)) for role, content, at in reversed(rows))
                facts = self._select_facts(session, query)
        except SQLAlchemyError as error:
            logger.warning("Memory recall failed error=%s", error)
            return MemoryContextSnapshot()
        summary = _clip(summary, query.max_characters)
        remaining = max(0, query.max_characters - len(summary))
        selected: list[str] = []
        for fact in facts:
            clipped = _clip(fact, remaining)
            if not clipped:
                break
            selected.append(clipped)
            remaining -= len(clipped)
        return MemoryContextSnapshot(summary, window, tuple(selected))

    def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None:
        """把一轮对话追加进窗口；溢出时把最旧消息浓缩进概要（LLM 摘要）。"""
        if self._engine is None or not content.strip():
            return
        with self._session() as session:
            session.add(MemoryMessageRow(scope=scope, role=role, content=content, at=at))
            count = (
                session.scalar(
                    select(func.count()).select_from(MemoryMessageRow).where(MemoryMessageRow.scope == scope)
                )
                or 0
            )
            if count > self._window_max:
                self._condense(session, scope, count - self._window_min)

    def remember(self, entry: MemoryEntry) -> bool:
        """终态投影：幂等回执 + 长期事实（窗口消息由 append_turn 负责）。"""
        if self._engine is None or not entry.input_summary.strip():
            return False
        with self._session() as session:
            result = session.execute(
                sqlite_insert(MemoryReceiptRow)
                .values(task_id=entry.task_id, scope=entry.scope, created_at=entry.created_at)
                .on_conflict_do_nothing(index_elements=["task_id"])
            )
            inserted = cast("CursorResult[Any]", result).rowcount
            if inserted == 0:
                return False
            for candidate in entry.fact_candidates:
                fact = candidate.strip()
                if fact:
                    session.execute(
                        sqlite_insert(DurableFactRow)
                        .values(
                            scope=entry.scope,
                            content=_clip(fact, 500),
                            source_task_id=entry.task_id,
                            created_at=entry.created_at,
                        )
                        .on_conflict_do_nothing(index_elements=["scope", "content"])
                    )
        if self._long_term is not None and entry.outcome_summary:
            self._long_term.add(entry.scope, f"{entry.input_summary}\n{entry.outcome_summary}", entry.created_at)
        return True

    def _condense(self, session: Session, scope: str, excess: int) -> None:
        """把最旧 ``excess`` 条消息 + 现有概要浓缩为新概要（LLM 或规则截断）。"""
        rows = (
            session.execute(
                select(MemoryMessageRow)
                .where(MemoryMessageRow.scope == scope)
                .order_by(MemoryMessageRow.seq.asc())
                .limit(excess)
            )
            .scalars()
            .all()
        )
        if not rows:
            return
        existing = session.scalar(select(SessionMemoryRow.summary).where(SessionMemoryRow.scope == scope))
        summary = str(existing) if existing else ""
        oldest = [{"role": row.role, "content": row.content, "at": row.at} for row in rows]
        condensed = self._summarize(summary, oldest)
        updated_at = datetime.now(UTC).isoformat()
        session.execute(
            sqlite_insert(SessionMemoryRow)
            .values(scope=scope, summary=condensed, updated_at=updated_at)
            .on_conflict_do_update(index_elements=["scope"], set_={"summary": condensed, "updated_at": updated_at})
        )
        session.execute(delete(MemoryMessageRow).where(MemoryMessageRow.seq.in_([row.seq for row in rows])))

    def _summarize(self, existing: str, messages: list[dict[str, Any]]) -> str:
        """LLM 浓缩（fast role）；网关不可用时规则截断。"""
        if self._gateway is None:
            combined = existing + "\n" + "\n".join(m["content"] for m in messages)
            return _tail(combined.strip(), _SUMMARY_LIMIT)
        import asyncio

        assert self._gateway is not None
        prompt = _Msg.SUMMARIZE_PROMPT.format(
            summary=existing or "（无）",
            messages="\n".join(f"{m['role']}: {m['content']}" for m in messages),
        )
        try:
            result = asyncio.run(self._gateway.get_response("fast", [{"role": "user", "content": prompt}]))
            text_value = str(result.get("text", "")).strip()
            if text_value:
                return _tail(text_value, _SUMMARY_LIMIT)
        except Exception as error:
            logger.warning("memory summarization failed error_type=%s", type(error).__name__)
        combined = existing + "\n" + "\n".join(m["content"] for m in messages)
        return _tail(combined.strip(), _SUMMARY_LIMIT)

    def _select_facts(self, session: Session, query: MemoryQuery) -> tuple[str, ...]:
        rows = (
            session.execute(
                select(DurableFactRow.content)
                .where(DurableFactRow.scope.in_((query.scope, "global")))
                .order_by(DurableFactRow.created_at.desc())
                .limit(max(query.fact_limit * 4, query.fact_limit))
            )
            .scalars()
            .all()
        )
        terms = {term.casefold() for term in query.query.split() if len(term) > 1}
        ranked = sorted(
            (str(value) for value in rows),
            key=lambda value: sum(term in value.casefold() for term in terms),
            reverse=True,
        )
        return tuple(ranked[: query.fact_limit])

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """事务上下文：成功提交，异常回滚。"""
        assert self._engine is not None
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise


def _build_engine(database_path: Path) -> "Engine":
    """构建同步 SQLite 引擎：NullPool + 默认隔离（读不占写锁）。"""
    engine = create_engine(
        f"sqlite:///{database_path}",
        poolclass=NullPool,
        connect_args={"timeout": 30},
    )

    def _set_busy_timeout(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.close()

    event.listen(engine, "connect", _set_busy_timeout)
    return engine


def _clip(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + _Msg.ELLIPSIS


def _tail(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return _Msg.ELLIPSIS + value[-(limit - 1) :]
