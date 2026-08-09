"""异步记忆编排：短期窗口、durable facts 与语义长期记忆。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from src.contracts import MemoryContextSnapshot, MemoryEntry, MemoryQuery
from src.memory.long_term import LongTermMemory
from src.memory.models import Base, DurableFactRow, MemoryReceiptRow
from src.memory.short_term import (
    DEFAULT_WINDOW_MAX,
    DEFAULT_WINDOW_MIN,
    ShortTermMemory,
    Summarizer,
    bounded_snapshot,
    clip,
)
from src.utils import get_logger
from src.utils.migration import initialize_storage

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence
    from pathlib import Path

    from sqlalchemy.engine import CursorResult, Engine


logger = get_logger("aurora.memory.service")


class MemoryService:
    """组合短期记忆、durable facts 与可降级语义长期记忆。"""

    def __init__(
        self,
        memory_dir: "Path | None" = None,
        *,
        gateway: Summarizer | None = None,
        embed_fn: "Callable[[list[str]], list[list[float]]] | None" = None,
        llm_model: str | None = None,
        window_min: int = DEFAULT_WINDOW_MIN,
        window_max: int = DEFAULT_WINDOW_MAX,
    ) -> None:
        self._engine: Engine | None = None
        self._short_term: ShortTermMemory | None = None
        if memory_dir is not None:
            memory_dir.mkdir(parents=True, exist_ok=True)
            self._engine = _build_engine(memory_dir / "memory.sqlite3")
            self._initialize()
            self._short_term = ShortTermMemory(
                self._engine,
                gateway=gateway,
                window_min=window_min,
                window_max=window_max,
            )
        self._long_term = (
            LongTermMemory(memory_dir, embed_fn=embed_fn, llm_model=llm_model) if memory_dir is not None else None
        )

    def _initialize(self) -> None:
        """配置 WAL，并创建或迁移 memory SQLite。"""
        from src.memory import migration

        assert self._engine is not None
        with self._engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))
            connection.execute(text("PRAGMA journal_size_limit=524288"))
            connection.execute(text("DROP TABLE IF EXISTS completed_tasks"))
            initialize_storage(
                connection,
                metadata=Base.metadata,
                steps=migration.STEPS,
                target=migration.TARGET_VERSION,
            )

    def history(self, *, scope: str | None = None, limit: int = 32) -> dict[str, Any]:
        """只读记忆历史：窗口、概要与 durable facts。"""
        if self._engine is None or self._short_term is None:
            return {"scope": scope, "window": [], "summaries": [], "facts": []}
        short_term = self._short_term.history(scope=scope, limit=limit)
        with self._session() as session:
            facts_query = select(DurableFactRow).order_by(DurableFactRow.created_at.desc()).limit(limit)
            if scope is not None:
                facts_query = facts_query.where(DurableFactRow.scope.in_((scope, "global")))
            facts = session.execute(facts_query).scalars().all()
        return {
            "scope": scope,
            **short_term,
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
        """只读记忆检索：语义优先，合并窗口和 durable facts 词项结果。"""
        if self._engine is None or self._short_term is None or not query.strip():
            return []
        terms = {term.casefold() for term in query.split() if len(term) > 1}
        if not terms:
            return []
        semantic = self._long_term.search(scope, query, limit) if self._long_term is not None and scope else ()
        candidates = [
            {"kind": "semantic", "scope": scope, "content": content, "hits": len(terms) + 1} for content in semantic
        ]
        candidates.extend(self._short_term.keyword_candidates(terms, scope))
        with self._session() as session:
            fact_rows = session.execute(select(DurableFactRow)).scalars().all()
        candidates.extend(_durable_candidates(fact_rows, terms, scope))
        candidates.sort(key=lambda item: item["hits"], reverse=True)
        return _unique_candidates(candidates, limit)

    def status(self) -> dict[str, Any]:
        """只读记忆统计与语义降级状态。"""
        if self._engine is None or self._short_term is None:
            return {
                "enabled": False,
                "window_messages": 0,
                "summaries": 0,
                "facts": 0,
                "scopes": [],
                "semantic": {"enabled": False, "degraded": True, "reason": "memory disabled"},
            }
        window_messages, summaries, scopes = self._short_term.counts_and_scopes()
        with self._session() as session:
            facts = session.scalar(select(func.count()).select_from(DurableFactRow)) or 0
        semantic = (
            self._long_term.status()
            if self._long_term is not None
            else {"enabled": False, "degraded": True, "reason": "semantic memory not configured"}
        )
        return {
            "enabled": True,
            "window_messages": window_messages,
            "summaries": summaries,
            "facts": facts,
            "scopes": scopes,
            "semantic": semantic,
        }

    async def recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
        """异步取得统一预算约束下的记忆快照。"""
        return await asyncio.to_thread(self._recall, query)

    def _recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
        if self._engine is None or self._short_term is None:
            return MemoryContextSnapshot()
        try:
            summary, window = self._short_term.load(query.scope)
            with self._session() as session:
                facts = self._select_facts(session, query)
        except SQLAlchemyError as error:
            logger.warning("Memory recall failed error=%s", error)
            return MemoryContextSnapshot()
        return bounded_snapshot(summary, window, facts, query.max_characters)

    async def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None:
        """把一轮对话追加到短期窗口，并按需生成异步概要。"""
        if self._short_term is None or not content.strip():
            return
        await self._short_term.append_turn(scope, role=role, content=content, at=at)

    async def remember(self, entry: MemoryEntry) -> bool:
        """幂等写入 durable facts，并异步投影到语义长期记忆。"""
        if self._engine is None or not entry.input_summary.strip():
            return False
        inserted = await asyncio.to_thread(self._remember, entry)
        if inserted and self._long_term is not None:
            content = "\n".join(
                part
                for part in (entry.input_summary, entry.outcome_summary or "", *entry.fact_candidates)
                if part.strip()
            )
            if content:
                await asyncio.to_thread(self._long_term.add, entry.scope, content, entry.created_at)
        return inserted

    def _remember(self, entry: MemoryEntry) -> bool:
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
                            content=clip(fact, 500),
                            source_task_id=entry.task_id,
                            created_at=entry.created_at,
                        )
                        .on_conflict_do_nothing(index_elements=["scope", "content"])
                    )
        return True

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
        semantic = (
            self._long_term.search(query.scope, query.query, query.fact_limit)
            if self._long_term is not None and query.query.strip()
            else ()
        )
        terms = {term.casefold() for term in query.query.split() if len(term) > 1}
        ranked = sorted(
            (str(value) for value in rows),
            key=lambda value: sum(term in value.casefold() for term in terms),
            reverse=True,
        )
        return tuple(dict.fromkeys((*semantic, *ranked)))[: query.fact_limit]

    @contextmanager
    def _session(self) -> "Generator[Session]":
        assert self._engine is not None
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise


def _build_engine(database_path: "Path") -> "Engine":
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


def _durable_candidates(rows: "Sequence[Any]", terms: set[str], scope: str | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
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
    return candidates


def _unique_candidates(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        content = str(item["content"])
        if content in seen:
            continue
        seen.add(content)
        unique.append(item)
    return unique[:limit]
