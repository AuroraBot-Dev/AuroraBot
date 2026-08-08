"""Schema v9 ORM 模型（RFC 0217，物理结构同 RFC 0210 不变）。

所有列名、类型、约束与索引（含部分唯一索引与 DESC 列序）逐一对齐
Schema v9；`create_all(checkfirst=True)` 只用于全新库，旧库经版本序列
迁移（src/engine/store/migration/，RFC 0217 §5）。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    TypeDecorator,
    desc,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.contracts import ActivityStatus, MessageStatus, TaskStatus

_SCHEMA_VERSION = 9


class Base(DeclarativeBase):
    """全部运行态表的声明式基类。"""


class CompactJSON(TypeDecorator[dict[str, Any]]):
    """JSON 列：保持紧凑序列化（sort_keys、紧凑分隔符，RFC 0210）不变。"""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: dict[str, Any] | None, dialect: Any) -> str | None:  # noqa: ARG002
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def process_result_value(self, value: str | None, dialect: Any) -> dict[str, Any] | None:  # noqa: ARG002
        return json.loads(value) if value is not None else None


SchemaMetaRow = Table(
    "schema_meta",
    Base.metadata,
    Column("version", Integer, nullable=False),
)


class TaskRow(Base):
    """tasks：Task 状态与资源预算（终态行即档案）。"""

    __tablename__ = "tasks"
    __table_args__ = (CheckConstraint("autonomous IN (0, 1)", name="tasks_autonomous_check"),)

    task_id: Mapped[str] = mapped_column("task_id", String, primary_key=True)
    root_agent_id: Mapped[str] = mapped_column("root_agent_id", String, nullable=False)
    root_message_id: Mapped[str] = mapped_column("root_message_id", String, nullable=False, unique=True)
    session_id: Mapped[str] = mapped_column("session_id", String, nullable=False)
    root_summary: Mapped[str] = mapped_column("root_summary", String, nullable=False)
    autonomous: Mapped[int] = mapped_column("autonomous", Integer, nullable=False)
    status: Mapped[str] = mapped_column("status", String, nullable=False)
    model_calls: Mapped[int] = mapped_column("model_calls", Integer, nullable=False)
    tool_calls: Mapped[int] = mapped_column("tool_calls", Integer, nullable=False)
    max_model_calls: Mapped[int] = mapped_column("max_model_calls", Integer, nullable=False)
    max_tool_calls: Mapped[int] = mapped_column("max_tool_calls", Integer, nullable=False)
    max_duration_seconds: Mapped[float] = mapped_column("max_duration_seconds", Float, nullable=False)
    started_at: Mapped[str] = mapped_column("started_at", String, nullable=False)
    updated_at: Mapped[str] = mapped_column("updated_at", String, nullable=False)
    termination_reason: Mapped[str | None] = mapped_column("termination_reason", String)

    agents: Mapped[list["AgentRow"]] = relationship(back_populates="task", passive_deletes=True)


class AgentRow(Base):
    """agents：同构 Agent 实例（RFC 0209）。"""

    __tablename__ = "agents"
    __table_args__ = (
        Index("idx_agents_task", "task_id", "status"),
        Index("idx_agents_parent", "parent_agent_id", "status"),
    )

    agent_id: Mapped[str] = mapped_column("agent_id", String, primary_key=True)
    task_id: Mapped[str] = mapped_column("task_id", String, ForeignKey("tasks.task_id"), nullable=False)
    parent_agent_id: Mapped[str | None] = mapped_column("parent_agent_id", String, ForeignKey("agents.agent_id"))
    profile_id: Mapped[str] = mapped_column("profile_id", String, nullable=False)
    depth: Mapped[int] = mapped_column("depth", Integer, nullable=False)
    assignment: Mapped[str] = mapped_column("assignment", String, nullable=False)
    status: Mapped[str] = mapped_column("status", String, nullable=False)
    state_json: Mapped[str] = mapped_column("state_json", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)
    updated_at: Mapped[str] = mapped_column("updated_at", String, nullable=False)
    last_summary: Mapped[str] = mapped_column("last_summary", String, nullable=False, server_default="")

    task: Mapped["TaskRow"] = relationship(back_populates="agents")
    parent: Mapped["AgentRow | None"] = relationship(remote_side=[agent_id])


class MessageRow(Base):
    """messages：Agent 邮箱（PENDING/PROCESSING/COMPLETED/ERROR）。"""

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_ready", "status", desc("priority"), "created_at"),
        Index("idx_messages_agent", "target_agent_id", "status", "created_at"),
    )

    message_id: Mapped[str] = mapped_column("message_id", String, primary_key=True)
    task_id: Mapped[str] = mapped_column("task_id", String, ForeignKey("tasks.task_id"), nullable=False)
    target_agent_id: Mapped[str] = mapped_column(
        "target_agent_id", String, ForeignKey("agents.agent_id"), nullable=False
    )
    message_type: Mapped[str] = mapped_column("type", String, nullable=False)
    payload_json: Mapped[str] = mapped_column("payload_json", String, nullable=False)
    causation_id: Mapped[str | None] = mapped_column("causation_id", String)
    correlation_id: Mapped[str] = mapped_column("correlation_id", String, nullable=False)
    priority: Mapped[int] = mapped_column("priority", Integer, nullable=False)
    status: Mapped[str] = mapped_column("status", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)
    completed_at: Mapped[str | None] = mapped_column("completed_at", String)

    task: Mapped["TaskRow"] = relationship()
    agent: Mapped["AgentRow"] = relationship()


class ActivityRow(Base):
    """activities：模型/工具活动请求与结果（kind 与部分唯一索引见 v9）。"""

    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("kind IN ('model', 'tool')", name="activities_kind_check"),
        Index("idx_activities_ready", "kind", "status", desc("priority"), "created_at"),
        Index(
            "idx_activities_one_active_per_agent",
            "agent_id",
            unique=True,
            sqlite_where=text("status IN ('PENDING', 'PROCESSING')"),
        ),
    )

    activity_id: Mapped[str] = mapped_column("activity_id", String, primary_key=True)
    task_id: Mapped[str] = mapped_column("task_id", String, ForeignKey("tasks.task_id"), nullable=False)
    agent_id: Mapped[str] = mapped_column("agent_id", String, ForeignKey("agents.agent_id"), nullable=False)
    kind: Mapped[str] = mapped_column("kind", String, nullable=False)
    request_json: Mapped[str] = mapped_column("request_json", String, nullable=False)
    status: Mapped[str] = mapped_column("status", String, nullable=False)
    priority: Mapped[int] = mapped_column("priority", Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column("idempotency_key", String, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)
    updated_at: Mapped[str] = mapped_column("updated_at", String, nullable=False)
    result_json: Mapped[str | None] = mapped_column("result_json", String)
    error: Mapped[str | None] = mapped_column("error", String)

    task: Mapped["TaskRow"] = relationship()
    agent: Mapped["AgentRow"] = relationship()


class CausalEventRow(Base):
    """causal_events：轻量因果审计（会话可读性来源，RFC 0210）。"""

    __tablename__ = "causal_events"
    __table_args__ = (Index("idx_causal_task", "task_id", "created_at"),)

    event_id: Mapped[str] = mapped_column("event_id", String, primary_key=True)
    task_id: Mapped[str | None] = mapped_column("task_id", String)
    agent_id: Mapped[str | None] = mapped_column("agent_id", String)
    event_type: Mapped[str] = mapped_column("type", String, nullable=False)
    summary: Mapped[str] = mapped_column("summary", String, nullable=False)
    payload_json: Mapped[str] = mapped_column("payload_json", String, nullable=False)
    causation_id: Mapped[str | None] = mapped_column("causation_id", String)
    correlation_id: Mapped[str] = mapped_column("correlation_id", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)


class InboxEventRow(Base):
    """inbox_events：持久化 Inbox（防抖批次与 triage 输入，RFC 0209）。"""

    __tablename__ = "inbox_events"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'TRIAGING', 'DEFERRED')", name="inbox_events_status_check"),
        Index("idx_inbox_due", "status", "available_at", desc("priority"), "created_at"),
        Index("idx_inbox_session", "session_id", "status", "created_at"),
    )

    event_id: Mapped[str] = mapped_column("event_id", String, primary_key=True)
    session_id: Mapped[str] = mapped_column("session_id", String, nullable=False)
    event_type: Mapped[str] = mapped_column("type", String, nullable=False)
    summary: Mapped[str] = mapped_column("summary", String, nullable=False)
    source_json: Mapped[str] = mapped_column("source_json", String, nullable=False)
    data_json: Mapped[str] = mapped_column("data_json", String, nullable=False)
    priority: Mapped[int] = mapped_column("priority", Integer, nullable=False)
    status: Mapped[str] = mapped_column("status", String, nullable=False)
    batch_id: Mapped[str | None] = mapped_column("batch_id", String)
    available_at: Mapped[str] = mapped_column("available_at", String, nullable=False)
    created_at: Mapped[str] = mapped_column("created_at", String, nullable=False)
    updated_at: Mapped[str] = mapped_column("updated_at", String, nullable=False)


# -- 状态字面量：从 contracts 枚举生成，禁止手写 ---------------------------------

AGENT_READY = "READY"
AGENT_CANCELLED = "CANCELLED"
AGENT_TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
MSG_PENDING = MessageStatus.PENDING
MSG_PROCESSING = MessageStatus.PROCESSING
MSG_COMPLETED = MessageStatus.COMPLETED
MSG_ERROR = MessageStatus.ERROR
ACT_PENDING = ActivityStatus.PENDING
ACT_PROCESSING = ActivityStatus.PROCESSING
ACT_COMPLETED = ActivityStatus.COMPLETED
ACT_ERROR = ActivityStatus.ERROR
ACT_CANCELLED = ActivityStatus.CANCELLED
ACT_ACTIVE = frozenset({ActivityStatus.PENDING, ActivityStatus.PROCESSING})
TASK_ACTIVE = TaskStatus.ACTIVE
