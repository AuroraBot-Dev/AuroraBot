"""Task、Agent、消息与因果事件查询（Schema v9，RFC 0217 ORM 实现）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, literal_column, or_, select

from src.contracts import AgentInstance, TaskState

from .base import RuntimeStoreBase, _loads, utc_now
from .models import (
    ACT_COMPLETED,
    ACT_ERROR,
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
        """导出会话的因果事件与模型输出投影（RFC 0210 会话可读性）。"""
        events = self.query_events(session_id=session_id, limit=100000)
        if not events:
            return None
        task_ids = tuple(dict.fromkeys(event["task_id"] for event in events if event["task_id"]))
        outputs: list[dict[str, Any]] = []
        if task_ids:
            rowid_column = literal_column("activities.rowid")
            statement = (
                select(ActivityRow, rowid_column)
                .where(
                    ActivityRow.task_id.in_(task_ids),
                    ActivityRow.kind == "model",
                    or_(ActivityRow.status == ACT_COMPLETED, ActivityRow.status == ACT_ERROR),
                )
                .order_by(rowid_column)
            )
            with self.session() as session:
                activity_rows = session.execute(statement).all()
            for activity, _rowid in activity_rows:
                kind = "error"
                text = str(activity.error) if activity.error else ""
                result = _loads(activity.result_json)
                if not activity.error and isinstance(result, dict) and isinstance(result.get("text"), str):
                    kind = "model"
                    text = result["text"]
                outputs.append(
                    {
                        "activity_id": str(activity.activity_id),
                        "task_id": str(activity.task_id),
                        "kind": kind,
                        "text": text,
                        "at": str(activity.updated_at),
                    }
                )
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
        """返回游标之后新增的模型输出文本，按活动行 ID 单调排序。

        kind 为 ``model`` 时取模型结果文本，为 ``error`` 时取失败信息；
        空文本的条目也返回，以便游标持续前进。
        """
        rowid_column = literal_column("activities.rowid")
        statement = (
            select(ActivityRow, TaskRow.session_id, rowid_column)
            .join(TaskRow, TaskRow.task_id == ActivityRow.task_id)
            .where(
                ActivityRow.kind == "model",
                or_(ActivityRow.status == ACT_COMPLETED, ActivityRow.status == ACT_ERROR),
                rowid_column > cursor,
            )
            .order_by(rowid_column)
            .limit(limit)
        )
        with self.session() as session:
            rows = session.execute(statement).all()
        items: list[dict[str, Any]] = []
        for activity, session_id, activity_rowid in rows:
            kind = "error"
            text = str(activity.error) if activity.error else ""
            result = _loads(activity.result_json)
            if not activity.error and isinstance(result, dict) and isinstance(result.get("text"), str):
                kind = "model"
                text = result["text"]
            items.append(
                {
                    "cursor": int(activity_rowid),
                    "activity_id": str(activity.activity_id),
                    "task_id": str(activity.task_id),
                    "session_id": str(session_id),
                    "kind": kind,
                    "text": text,
                    "at": str(activity.updated_at),
                }
            )
        return tuple(items)

    def counts(self) -> dict[str, int]:
        with self.session() as session:
            inbox_total = session.scalar(select(func.count()).select_from(InboxEventRow)) or 0
            due_sessions = (
                session.scalar(
                    select(func.count(func.distinct(InboxEventRow.session_id))).where(
                        InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)),
                        InboxEventRow.available_at <= utc_now(),
                    )
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
        return {
            "inbox_events": inbox_total,
            "due_inbox_sessions": due_sessions,
            "active_tasks": active_tasks,
            "active_agents": active_agents,
            "pending_messages": pending_messages,
            "pending_activities": pending_activities,
            "pending_model_activities": pending_model,
            "pending_tool_activities": pending_tool,
        }
