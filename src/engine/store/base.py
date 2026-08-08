"""SQLAlchemy 引擎、Schema v9 初始化与实体转换，供所有 Store Mixin 共享。

所有写操作均通过 session() 事务上下文执行（引擎级 isolation_level=IMMEDIATE，
等价 RFC 0210 的 BEGIN IMMEDIATE）；单进程 asyncio 独占，无租约与乐观锁。
初始化：全新库直接建 v9 Schema；v1-v8 旧库按版本序列迁移到 v9
（src/engine/store/migration/，RFC 0217 §5）。connect()/transaction() 保留
为原始 sqlite3 逃生口（测试与调试直查 DB 用，热路径不使用）。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

from src.contracts import (
    ActivityRequest,
    ActivityStatus,
    AgentInstance,
    AgentMessage,
    AgentStatus,
    MessageStatus,
    TaskState,
    TaskStatus,
)
from src.utils import utc_now
from src.utils.migration import migrate_to

from .models import (
    ACT_PROCESSING,
    MSG_PENDING,
    MSG_PROCESSING,
    ActivityRow,
    Base,
    CausalEventRow,
    InboxEventRow,
    MessageRow,
)


def _json(value: object) -> str:
    """将 Python 对象序列化为紧凑 JSON 字符串，用于统一所有 JSON 列的存储格式。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _loads(value: str | None) -> Any:
    """解析 JSON 列（None 保持 None）。"""
    return json.loads(value) if value is not None else None


def _configure_dbapi(dbapi_connection: Any, _record: Any) -> None:
    """连接级 PRAGMA：外键与忙碌超时（等价原 connect() 配置）。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA busy_timeout = 30000")
    cursor.close()


def _read_schema_version(connection: Any) -> int:
    """读取 schema_meta 版本号；无 schema_meta 表（全新库）视为 v0。"""
    has_meta = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'")
    ).scalar()
    if not has_meta:
        return 0
    version = connection.execute(text("SELECT version FROM schema_meta LIMIT 1")).scalar()
    return int(version) if version is not None else 0


def _write_schema_version(connection: Any, version: int) -> None:
    """覆写 schema_meta 版本号（单行表，先清后写）。"""
    connection.execute(text("DELETE FROM schema_meta"))
    connection.execute(text("INSERT INTO schema_meta(version) VALUES (:version)"), {"version": version})


class RuntimeStoreBase:
    """事务型持久化仓库基类。调用者将模型和平台 I/O 置于事务外部。"""

    def __init__(self, database_path: Path) -> None:
        """初始化仓库基类，接收 SQLite 数据库文件路径并构建 ORM 引擎。"""
        self.database_path = database_path
        self._engine = _build_engine(database_path)

    def connect(self) -> sqlite3.Connection:
        """原始 sqlite3 逃生口：测试与调试直查 DB（热路径不使用）。"""
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """原始 sqlite3 事务逃生口（BEGIN IMMEDIATE，异常自动回滚）。"""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """ORM 事务上下文：BEGIN IMMEDIATE，提交后属性不过期便于外部读取。"""
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield session

    def initialize(self) -> None:
        """初始化运行时数据库：全新库建 v9 Schema，旧库按版本序列迁移到 v9。

        版本号存于 schema_meta（无表 = v0 全新库）；v0 直接建表并写入
        当前目标版本；v1-v8 旧库经 src/engine/store/migration/ 版本序列
        升级到 v9（RFC 0217 §5）。迁移在单个事务中执行，任一版本步骤
        失败整体回滚。
        """
        from . import migration

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA journal_size_limit = 1048576")
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        with self._engine.begin() as connection:
            current = _read_schema_version(connection)
            if current == 0:
                Base.metadata.create_all(bind=connection, checkfirst=True)
                _write_schema_version(connection, migration.TARGET_VERSION)
                current = migration.TARGET_VERSION
            migrate_to(
                connection,
                current=current,
                target=migration.TARGET_VERSION,
                steps=migration.STEPS,
                set_version=_write_schema_version,
            )
        self.recover_interrupted()

    def recover_interrupted(self) -> None:
        """崩溃恢复：处理中的消息回到 PENDING，中断的 model Activity 标 ERROR 并通知。"""
        now = utc_now()
        with self.session() as session:
            session.execute(
                update(MessageRow)
                .where(MessageRow.status == MSG_PROCESSING)
                .values(status=MSG_PENDING, completed_at=None)
            )
            session.execute(
                update(InboxEventRow).where(InboxEventRow.status == "TRIAGING").values(status="PENDING", batch_id=None)
            )
            interrupted = session.execute(
                select(ActivityRow).where(ActivityRow.status == ACT_PROCESSING, ActivityRow.kind == "model")
            ).scalars()
            for row in interrupted:
                row.status = "ERROR"
                row.error = "interrupted_by_restart"
                row.updated_at = now
                self._insert_message(
                    session,
                    task_id=str(row.task_id),
                    target_agent_id=str(row.agent_id),
                    message_type="model.failed",
                    payload={"activity_id": row.activity_id, "error": "interrupted_by_restart"},
                    causation_id=str(row.activity_id),
                    correlation_id=str(row.task_id),
                    priority=int(row.priority),
                    now=now,
                )

    @staticmethod
    def _task(row: Any) -> TaskState:
        """将 tasks 表实体转换为 TaskState 领域模型。"""
        return TaskState(
            task_id=str(row.task_id),
            root_agent_id=str(row.root_agent_id),
            root_message_id=str(row.root_message_id),
            session_id=str(row.session_id),
            root_summary=str(row.root_summary),
            autonomous=bool(row.autonomous),
            status=TaskStatus(row.status),
            model_calls=int(row.model_calls),
            tool_calls=int(row.tool_calls),
            max_model_calls=int(row.max_model_calls),
            max_tool_calls=int(row.max_tool_calls),
            max_duration_seconds=float(row.max_duration_seconds),
            started_at=str(row.started_at),
            updated_at=str(row.updated_at),
            termination_reason=row.termination_reason,
        )

    @staticmethod
    def _agent(row: Any) -> AgentInstance:
        """将 agents 表实体转换为 AgentInstance 领域模型。"""
        return AgentInstance(
            agent_id=str(row.agent_id),
            task_id=str(row.task_id),
            parent_agent_id=row.parent_agent_id,
            profile_id=str(row.profile_id),
            depth=int(row.depth),
            assignment=str(row.assignment),
            status=AgentStatus(row.status),
            state=_loads(row.state_json),
            created_at=str(row.created_at),
            updated_at=str(row.updated_at),
            last_summary=str(row.last_summary),
        )

    @staticmethod
    def _message(row: Any) -> AgentMessage:
        """将 messages 表实体转换为 AgentMessage 领域模型。"""
        return AgentMessage(
            message_id=str(row.message_id),
            task_id=str(row.task_id),
            target_agent_id=str(row.target_agent_id),
            type=str(row.message_type),
            payload=_loads(row.payload_json),
            causation_id=row.causation_id,
            correlation_id=str(row.correlation_id),
            priority=int(row.priority),
            status=MessageStatus(row.status),
            created_at=str(row.created_at),
        )

    @staticmethod
    def _activity(row: Any) -> ActivityRequest:
        """将 activities 表实体转换为 ActivityRequest 领域模型。"""
        return ActivityRequest(
            activity_id=str(row.activity_id),
            task_id=str(row.task_id),
            agent_id=str(row.agent_id),
            kind=row.kind,
            request=_loads(row.request_json),
            status=ActivityStatus(row.status),
            priority=int(row.priority),
            idempotency_key=str(row.idempotency_key),
            created_at=str(row.created_at),
        )

    @staticmethod
    def _insert_message(
        session: Session,
        *,
        task_id: str,
        target_agent_id: str,
        message_type: str,
        payload: dict[str, Any],
        causation_id: str | None,
        correlation_id: str,
        priority: int,
        now: str,
    ) -> str:
        """向邮箱插入一条新消息并返回 message_id。所有消息创建均通过此方法。"""
        message_id = str(uuid4())
        session.add(
            MessageRow(
                message_id=message_id,
                task_id=task_id,
                target_agent_id=target_agent_id,
                message_type=message_type,
                payload_json=_json(payload),
                causation_id=causation_id,
                correlation_id=correlation_id,
                priority=priority,
                status=MessageStatus.PENDING,
                created_at=now,
            )
        )
        return message_id

    @staticmethod
    def _insert_causal_event(
        session: Session,
        *,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
        correlation_id: str,
        task_id: str | None = None,
        agent_id: str | None = None,
        causation_id: str | None = None,
        now: str,
    ) -> str:
        """向 causal_events 插入一条因果事件并返回 event_id（载荷为轻量摘要，RFC 0210）。"""
        event_id = str(uuid4())
        session.add(
            CausalEventRow(
                event_id=event_id,
                task_id=task_id,
                agent_id=agent_id,
                event_type=event_type,
                summary=summary,
                payload_json=_json(payload),
                causation_id=causation_id,
                correlation_id=correlation_id,
                created_at=now,
            )
        )
        return event_id


def _build_engine(database_path: Path) -> Engine:
    """构建同步 SQLite 引擎：NullPool + 驱动级 BEGIN IMMEDIATE + PRAGMA 事件。"""
    engine = create_engine(
        f"sqlite:///{database_path}",
        poolclass=NullPool,
        connect_args={"timeout": 30, "isolation_level": "IMMEDIATE"},
    )
    event.listen(engine, "connect", _configure_dbapi)
    return engine
