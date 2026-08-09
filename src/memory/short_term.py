"""短期记忆窗口、异步概要与统一快照预算。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.contracts import MemoryContextSnapshot, MemoryMessage, RemoteMessage, RemoteSummary
from src.memory.models import MemoryMessageRow, SessionMemoryRow
from src.utils import get_logger, utc_now

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sqlalchemy.engine import Engine


class Summarizer(Protocol):
    """概要生成所需的模型网关窄面。"""

    async def get_response(self, role: str, inputs: list[dict]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CondenseBatch:
    """一次窗口压缩所需的不可变输入。"""

    existing: str
    messages: tuple[dict[str, str], ...]
    message_ids: tuple[int, ...]


class _Msg(StrEnum):
    ELLIPSIS = "…"
    SUMMARIZE_PROMPT = (
        "你负责记忆浓缩：把『最早记忆项』与一批旧对话再次压缩为一条更浓缩的"
        "记忆项（保留关键事实，丢弃已失去时效的细节）。\n"
        "最早记忆项：\n{summary}\n\n旧对话：\n{messages}\n\n只输出新的记忆项文本。"
    )


logger = get_logger("aurora.memory.short_term")
_SUMMARY_LIMIT = 2400
DEFAULT_WINDOW_MIN = 100
DEFAULT_WINDOW_MAX = 300
_REMOTE_BUDGET_DIVISOR = 3
_REMOTE_BUDGET_MAX = 8000


class ShortTermMemory:
    """在 memory SQLite 上实现窗口、概要和词项窗口检索。"""

    def __init__(
        self,
        engine: "Engine",
        *,
        gateway: Summarizer | None,
        window_min: int,
        window_max: int,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self.window_min = window_min
        self.window_max = window_max

    def history(self, *, scope: str | None, limit: int) -> dict[str, list[dict[str, str]]]:
        """返回窗口消息与会话概要的只读投影。"""
        with self._session() as session:
            window_query = select(MemoryMessageRow).order_by(MemoryMessageRow.seq.desc()).limit(limit)
            if scope is not None:
                window_query = window_query.where(MemoryMessageRow.scope == scope)
            messages = session.execute(window_query).scalars().all()
            summary_query = select(SessionMemoryRow).order_by(SessionMemoryRow.updated_at.desc())
            if scope is not None:
                summary_query = summary_query.where(SessionMemoryRow.scope == scope)
            summaries = session.execute(summary_query).scalars().all()
        return {
            "window": [
                {"scope": row.scope, "role": row.role, "content": row.content, "at": row.at}
                for row in reversed(messages)
            ],
            "summaries": [
                {"scope": row.scope, "summary": row.summary, "updated_at": row.updated_at} for row in summaries
            ],
        }

    def load(self, scope: str) -> tuple[str, tuple[MemoryMessage, ...]]:
        """读取一个 scope 的概要与时间正序窗口。"""
        with self._session() as session:
            row = session.scalar(select(SessionMemoryRow.summary).where(SessionMemoryRow.scope == scope))
            summary = str(row) if row is not None else ""
            rows = session.execute(
                select(MemoryMessageRow.role, MemoryMessageRow.content, MemoryMessageRow.at)
                .where(MemoryMessageRow.scope == scope)
                .order_by(MemoryMessageRow.seq.desc())
                .limit(self.window_max)
            ).all()
        window = tuple(MemoryMessage(str(role), str(content), str(at)) for role, content, at in reversed(rows))
        return summary, window

    def keyword_candidates(self, terms: set[str], scope: str | None) -> list[dict[str, Any]]:
        """返回窗口消息的词项匹配候选。"""
        with self._session() as session:
            rows = session.execute(select(MemoryMessageRow)).scalars().all()
        return _window_candidates(rows, terms, scope)

    async def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None:
        """追加一轮原文；超过上界时异步生成概要并压缩回下界。"""
        batch = await asyncio.to_thread(self._append, scope, role, content, at)
        if batch is None:
            return
        condensed = await self._summarize(batch.existing, list(batch.messages))
        await asyncio.to_thread(self._store_condensed, scope, batch.message_ids, condensed)

    def counts_and_scopes(self) -> tuple[int, int, list[str]]:
        """返回窗口数、概要数和窗口 scope。"""
        with self._session() as session:
            window_messages = session.scalar(select(func.count()).select_from(MemoryMessageRow)) or 0
            summaries = session.scalar(select(func.count()).select_from(SessionMemoryRow)) or 0
            scope_statement = select(MemoryMessageRow.scope).distinct().order_by(MemoryMessageRow.scope)
            scopes = [str(value) for value in session.execute(scope_statement).scalars().all()]
        return int(window_messages), int(summaries), scopes

    def _append(self, scope: str, role: str, content: str, at: str) -> CondenseBatch | None:
        with self._session() as session:
            session.add(MemoryMessageRow(scope=scope, role=role, content=content, at=at))
            session.flush()
            count = (
                session.scalar(
                    select(func.count()).select_from(MemoryMessageRow).where(MemoryMessageRow.scope == scope)
                )
                or 0
            )
            if count > self.window_max:
                return self._condense_batch(session, scope, count - self.window_min)
        return None

    @staticmethod
    def _condense_batch(session: Session, scope: str, excess: int) -> CondenseBatch | None:
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
            return None
        existing = session.scalar(select(SessionMemoryRow.summary).where(SessionMemoryRow.scope == scope))
        messages = tuple({"role": row.role, "content": row.content, "at": row.at} for row in rows)
        return CondenseBatch(str(existing) if existing else "", messages, tuple(row.seq for row in rows))

    def _store_condensed(self, scope: str, message_ids: tuple[int, ...], condensed: str) -> None:
        updated_at = utc_now()
        with self._session() as session:
            session.execute(
                sqlite_insert(SessionMemoryRow)
                .values(scope=scope, summary=condensed, updated_at=updated_at)
                .on_conflict_do_update(index_elements=["scope"], set_={"summary": condensed, "updated_at": updated_at})
            )
            session.execute(delete(MemoryMessageRow).where(MemoryMessageRow.seq.in_(message_ids)))

    async def _summarize(self, existing: str, messages: list[dict[str, Any]]) -> str:
        combined = existing + "\n" + "\n".join(message["content"] for message in messages)
        fallback = tail(combined.strip(), _SUMMARY_LIMIT)
        if self._gateway is None:
            return fallback
        prompt = _Msg.SUMMARIZE_PROMPT.format(
            summary=existing or "（无）",
            messages="\n".join(f"{message['role']}: {message['content']}" for message in messages),
        )
        try:
            result = await self._gateway.get_response("fast", [{"role": "user", "content": prompt}])
            text_value = str(result.get("text", "")).strip()
            if text_value:
                return tail(text_value, _SUMMARY_LIMIT)
        except Exception as error:  # noqa: BLE001
            logger.warning("memory summarization failed error_type=%s", type(error).__name__)
        return fallback

    @contextmanager
    def _session(self) -> "Iterator[Session]":
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise


def bounded_snapshot(
    summary: str,
    window: tuple[MemoryMessage, ...],
    remote_summaries: tuple[RemoteSummary, ...],
    remote_window: tuple[RemoteMessage, ...],
    facts: tuple[str, ...],
    limit: int,
) -> MemoryContextSnapshot:
    """按本域概要、本域窗口、跨域概要、跨域尾部、相关事实的固定顺序消费统一字符预算。

    本域窗口最多消费除去保障预算后的剩余部分：跨域动态与事实合计至少保留
    ``min(remaining // 3, 8000)`` 字符，避免本域原文占满预算后跨域动态不可见。
    """
    remaining = max(0, limit)
    bounded_summary = clip(summary, remaining)
    remaining -= len(bounded_summary)

    floor = min(remaining // _REMOTE_BUDGET_DIVISOR, _REMOTE_BUDGET_MAX)
    window_budget = max(0, remaining - floor)
    selected_window: list[MemoryMessage] = []
    window_used = 0
    for message in reversed(window):
        content = clip(message.content, window_budget - window_used)
        if not content:
            break
        selected_window.append(MemoryMessage(message.role, content, message.at))
        window_used += len(content)
    selected_window.reverse()
    remaining -= window_used

    selected_remote_summaries: list[RemoteSummary] = []
    for item in remote_summaries:
        content = clip(item.summary, remaining)
        if not content:
            break
        selected_remote_summaries.append(RemoteSummary(item.scope, content, item.updated_at))
        remaining -= len(content)

    selected_remote_window: list[RemoteMessage] = []
    for message in reversed(remote_window):
        content = clip(message.content, remaining)
        if not content:
            break
        selected_remote_window.append(RemoteMessage(message.scope, message.role, content, message.at))
        remaining -= len(content)
    selected_remote_window.reverse()

    selected_facts: list[str] = []
    for fact in facts:
        content = clip(fact, remaining)
        if not content:
            break
        selected_facts.append(content)
        remaining -= len(content)
    return MemoryContextSnapshot(
        bounded_summary,
        tuple(selected_window),
        tuple(selected_remote_summaries),
        tuple(selected_remote_window),
        tuple(selected_facts),
    )


def clip(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + _Msg.ELLIPSIS


def tail(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return _Msg.ELLIPSIS + value[-(limit - 1) :]


def _window_candidates(rows: "Sequence[Any]", terms: set[str], scope: str | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
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
    return candidates
