"""Task、Agent、消息、会话 generation 与因果事件查询（Schema v10，SQLAlchemy ORM 实现）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, literal_column, select

from src.contracts import AgentInstance, TaskState

from .base import RuntimeStoreBase, _loads, utc_now
from .models import (
    ACT_PENDING,
    AGENT_TERMINAL,
    INBOX_DEFERRED,
    INBOX_PENDING,
    MSG_PENDING,
    TASK_ACTIVE,
    ActivityRow,
    AgentRow,
    CausalEventRow,
    InboxEventRow,
    MessageRow,
    OutputPublicationRow,
    SessionLaneRow,
    TaskRow,
)


class StoreRuntimeMixin(RuntimeStoreBase):
    """运行态只读查询与状态 CRUD。"""

    def get_task(self, task_id: str) -> TaskState | None:
        with self.session() as session:
            row = session.scalar(select(TaskRow).where(TaskRow.task_id == task_id))
            return self._task(row) if row is not None else None

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        with self.session() as session:
            row = session.scalar(select(AgentRow).where(AgentRow.agent_id == agent_id))
            return self._agent(row) if row is not None else None

    def children(self, agent_id: str) -> tuple[AgentInstance, ...]:
        with self.session() as session:
            rows = session.execute(
                select(AgentRow)
                .where(AgentRow.parent_agent_id == agent_id)
                .order_by(AgentRow.created_at, AgentRow.agent_id)
            ).scalars()
            return tuple(self._agent(row) for row in rows)

    def tasks(
        self,
        *,
        active_only: bool = False,
        status: str | None = None,
        limit: int | None = None,
    ) -> tuple[TaskState, ...]:
        statement = select(TaskRow).order_by(TaskRow.started_at, TaskRow.task_id)
        if active_only:
            statement = statement.where(TaskRow.status == TASK_ACTIVE)
        if status is not None:
            statement = statement.where(TaskRow.status == status)
        if limit is not None:
            statement = statement.limit(limit)
        with self.session() as session:
            return tuple(self._task(row) for row in session.execute(statement).scalars())

    def agents(self, *, active_only: bool = False, limit: int | None = None) -> tuple[AgentInstance, ...]:
        statement = select(AgentRow).order_by(AgentRow.created_at, AgentRow.agent_id)
        if active_only:
            statement = statement.where(AgentRow.status.not_in(AGENT_TERMINAL))
        if limit is not None:
            statement = statement.limit(limit)
        with self.session() as session:
            return tuple(self._agent(row) for row in session.execute(statement).scalars())

    def messages_for_agent(self, agent_id: str) -> tuple[dict[str, Any], ...]:
        with self.session() as session:
            rows = session.execute(
                select(MessageRow)
                .where(MessageRow.target_agent_id == agent_id)
                .order_by(MessageRow.created_at, MessageRow.message_id)
            ).scalars()
            return tuple(self._message(row).to_dict() for row in rows)

    def has_pending_child_reports(self, agent_id: str) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(MessageRow.message_id)
                .where(
                    MessageRow.target_agent_id == agent_id,
                    MessageRow.message_type.in_(("child.completed", "child.failed")),
                    MessageRow.status == MSG_PENDING,
                )
                .limit(1)
            )
            return row is not None

    def events_for_task(self, task_id: str) -> tuple[dict[str, Any], ...]:
        with self.session() as session:
            rows = session.execute(
                select(CausalEventRow)
                .where(CausalEventRow.task_id == task_id)
                .order_by(CausalEventRow.created_at, CausalEventRow.event_id)
            ).scalars()
            return tuple(
                {
                    "event_id": row.event_id,
                    "task_id": row.task_id,
                    "agent_id": row.agent_id,
                    "type": row.event_type,
                    "summary": row.summary,
                    "payload": _loads(row.payload_json),
                    "causation_id": row.causation_id,
                    "correlation_id": row.correlation_id,
                    "created_at": row.created_at,
                }
                for row in rows
            )

    def query_events(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        event_type: str | None = None,
        after_id: int = 0,
        limit: int = 64,
    ) -> tuple[dict[str, Any], ...]:
        """按条件筛选因果事件流，after_id 为 causal_events 行号游标（单调递增）。"""
        rowid_column = literal_column("causal_events.rowid")
        statement = select(CausalEventRow, rowid_column).order_by(rowid_column).where(rowid_column > after_id)
        if session_id is not None:
            statement = statement.where(
                CausalEventRow.task_id.in_(select(TaskRow.task_id).where(TaskRow.session_id == session_id))
            )
        if task_id is not None:
            statement = statement.where(CausalEventRow.task_id == task_id)
        if event_type is not None:
            statement = statement.where(CausalEventRow.event_type == event_type)
        statement = statement.limit(limit)
        with self.session() as session:
            rows = session.execute(statement).all()
        return tuple(self._causal_event(row) for row in rows)

    def session_export(self, session_id: str) -> dict[str, Any] | None:
        """导出会话因果事件与已通过 generation 提交屏障的输出。"""
        events = self.query_events(session_id=session_id, limit=100000)
        if not events:
            return None
        with self.session() as session:
            rows = session.scalars(
                select(OutputPublicationRow)
                .where(OutputPublicationRow.session_id == session_id)
                .order_by(OutputPublicationRow.seq)
            ).all()
        outputs = [
            {
                "activity_id": str(row.activity_id),
                "task_id": str(row.task_id),
                "kind": str(row.kind),
                "text": str(row.text),
                "at": str(row.created_at),
            }
            for row in rows
        ]
        return {"session_id": session_id, "events": events, "outputs": outputs}

    @staticmethod
    def _causal_event(row: Any) -> dict[str, Any]:
        """将因果事件行投影为只读字典。"""
        event, _rowid = row
        return {
            "event_id": event.event_id,
            "task_id": event.task_id,
            "agent_id": event.agent_id,
            "type": event.event_type,
            "summary": event.summary,
            "payload": _loads(event.payload_json),
            "causation_id": event.causation_id,
            "correlation_id": event.correlation_id,
            "created_at": event.created_at,
        }

    def recent_outputs(self, cursor: int = 0, *, limit: int = 64) -> tuple[dict[str, Any], ...]:
        """返回提交屏障之后的单调用户输出流；superseded generation 永不进入此表。"""
        statement = (
            select(OutputPublicationRow)
            .where(OutputPublicationRow.seq > cursor)
            .order_by(OutputPublicationRow.seq)
            .limit(limit)
        )
        with self.session() as session:
            rows = session.scalars(statement).all()
        return tuple(
            {
                "cursor": int(row.seq),
                "activity_id": str(row.activity_id),
                "task_id": str(row.task_id),
                "session_id": str(row.session_id),
                "kind": str(row.kind),
                "text": str(row.text),
                "at": str(row.created_at),
            }
            for row in rows
        )

    def recent_outputs_tail(self) -> int:
        """当前已提交输出流的最大 publication sequence。"""
        with self.session() as session:
            value = session.scalar(select(func.max(OutputPublicationRow.seq)))
        return int(value) if value is not None else 0

    def session_lane(self, session_id: str) -> dict[str, Any] | None:
        """返回会话 revision、watermark 与当前活动 generation。"""
        with self.session() as session:
            row = session.get(SessionLaneRow, session_id)
            if row is None:
                return None
            return {
                "session_id": str(row.session_id),
                "observed_revision": int(row.observed_revision),
                "generation_revision": int(row.generation_revision),
                "committed_revision": int(row.committed_revision),
                "generation_watermark": int(row.generation_watermark),
                "active_task_id": row.active_task_id,
                "interrupt_count": int(row.interrupt_count),
                "generation_started_at": row.generation_started_at,
                "updated_at": str(row.updated_at),
            }

    def counts(self) -> dict[str, int]:
        with self.session() as session:
            inbox_total = session.scalar(select(func.count()).select_from(InboxEventRow)) or 0
            due_sessions = (
                session.scalar(
                    select(func.count(func.distinct(InboxEventRow.session_id)))
                    .where(
                        InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)),
                        InboxEventRow.available_at <= utc_now(),
                        SessionLaneRow.active_task_id.is_(None),
                    )
                    .join(SessionLaneRow, SessionLaneRow.session_id == InboxEventRow.session_id)
                )
                or 0
            )
            active_tasks = (
                session.scalar(select(func.count()).select_from(TaskRow).where(TaskRow.status == TASK_ACTIVE)) or 0
            )
            active_agents = (
                session.scalar(select(func.count()).select_from(AgentRow).where(AgentRow.status.not_in(AGENT_TERMINAL)))
                or 0
            )
            pending_messages = (
                session.scalar(select(func.count()).select_from(MessageRow).where(MessageRow.status == MSG_PENDING))
                or 0
            )
            pending_activities = (
                session.scalar(select(func.count()).select_from(ActivityRow).where(ActivityRow.status == ACT_PENDING))
                or 0
            )
            pending_model = (
                session.scalar(
                    select(func.count())
                    .select_from(ActivityRow)
                    .where(ActivityRow.kind == "model", ActivityRow.status == ACT_PENDING)
                )
                or 0
            )
            pending_tool = (
                session.scalar(
                    select(func.count())
                    .select_from(ActivityRow)
                    .where(ActivityRow.kind == "tool", ActivityRow.status == ACT_PENDING)
                )
                or 0
            )
            active_generations = (
                session.scalar(
                    select(func.count()).select_from(SessionLaneRow).where(SessionLaneRow.active_task_id.is_not(None))
                )
                or 0
            )
        return {
            "inbox_events": inbox_total,
            "due_inbox_sessions": due_sessions,
            "active_tasks": active_tasks,
            "active_agents": active_agents,
            "pending_messages": pending_messages,
            "pending_activities": pending_activities,
            "pending_model_activities": pending_model,
            "pending_tool_activities": pending_tool,
            "active_generations": active_generations,
        }
