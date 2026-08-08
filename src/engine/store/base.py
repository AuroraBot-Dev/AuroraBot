"""SQLite 连接管理、Schema v9 初始化与行数据转换，供所有 Store Mixin 共享。

所有写操作均通过 transaction() 上下文管理器执行；单进程 asyncio 独占，
无租约与乐观锁（RFC 0210）。初始化只接受全新 v9 库，旧库拒绝启动。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

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

from .schema import _ACTIVE_ACTIVITY_INDEX, _SCHEMA, _SCHEMA_VERSION
from .status import (
    ACT_PROCESSING,
    MSG_PENDING,
    MSG_PROCESSING,
)


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    UNSUPPORTED_SCHEMA = "不支持的 Agent 运行时数据库 Schema 版本（仅接受全新 v9，旧工作区请重建）"


def _json(value: object) -> str:
    """将 Python 对象序列化为紧凑 JSON 字符串，用于统一所有 JSON 列的存储格式。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class RuntimeStoreBase:
    """事务型持久化仓库基类。调用者将模型和平台 I/O 置于事务外部。"""

    def __init__(self, database_path: Path) -> None:
        """初始化仓库基类，接收 SQLite 数据库文件路径。"""
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        """创建并返回新的 SQLite 连接，配置 Row 工厂和外键/超时参数。"""
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文管理器。使用 BEGIN IMMEDIATE 获取写锁，异常时自动回滚。"""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def initialize(self) -> None:
        """初始化运行时数据库：创建 v9 Schema，拒绝旧库。"""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA journal_size_limit = 1048576")
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
            connection.executescript(_SCHEMA)
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            version = int(row["version"]) if row is not None else None
            if version is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (_SCHEMA_VERSION,))
            elif version != _SCHEMA_VERSION:
                raise RuntimeError(_Msg.UNSUPPORTED_SCHEMA)
            connection.execute(_ACTIVE_ACTIVITY_INDEX)
            connection.commit()
        self.recover_interrupted()

    def recover_interrupted(self) -> None:
        """崩溃恢复：处理中的消息回到 PENDING，中断的 model Activity 标 ERROR 并通知。"""
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE messages SET status = {MSG_PENDING}, completed_at = NULL WHERE status = {MSG_PROCESSING}"
            )
            connection.execute("UPDATE inbox_events SET status = 'PENDING', batch_id = NULL WHERE status = 'TRIAGING'")
            interrupted = connection.execute(
                f"SELECT * FROM activities WHERE status = {ACT_PROCESSING} AND kind = 'model'"
            ).fetchall()
            for row in interrupted:
                connection.execute(
                    "UPDATE activities SET status = 'ERROR', error = ?, updated_at = ? WHERE activity_id = ?",
                    ("interrupted_by_restart", now, row["activity_id"]),
                )
                self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type="model.failed",
                    payload={"activity_id": row["activity_id"], "error": "interrupted_by_restart"},
                    causation_id=str(row["activity_id"]),
                    correlation_id=str(row["task_id"]),
                    priority=int(row["priority"]),
                    now=now,
                )
            connection.execute(
                f"UPDATE activities SET status = 'PROCESSING', updated_at = ? "
                f"WHERE status = {ACT_PROCESSING} AND kind = 'tool'",
                (now,),
            )

    @staticmethod
    def _task(row: sqlite3.Row) -> TaskState:
        """将 tasks 表的数据库行转换为 TaskState 领域模型。"""
        return TaskState(
            task_id=str(row["task_id"]),
            root_agent_id=str(row["root_agent_id"]),
            root_message_id=str(row["root_message_id"]),
            session_id=str(row["session_id"]),
            root_summary=str(row["root_summary"]),
            autonomous=bool(row["autonomous"]),
            status=TaskStatus(row["status"]),
            model_calls=int(row["model_calls"]),
            tool_calls=int(row["tool_calls"]),
            max_model_calls=int(row["max_model_calls"]),
            max_tool_calls=int(row["max_tool_calls"]),
            max_duration_seconds=float(row["max_duration_seconds"]),
            started_at=str(row["started_at"]),
            updated_at=str(row["updated_at"]),
            termination_reason=row["termination_reason"],
        )

    @staticmethod
    def _agent(row: sqlite3.Row) -> AgentInstance:
        """将 agents 表的数据库行转换为 AgentInstance 领域模型。"""
        return AgentInstance(
            agent_id=str(row["agent_id"]),
            task_id=str(row["task_id"]),
            parent_agent_id=row["parent_agent_id"],
            profile_id=str(row["profile_id"]),
            depth=int(row["depth"]),
            assignment=str(row["assignment"]),
            status=AgentStatus(row["status"]),
            state=json.loads(row["state_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_summary=str(row["last_summary"]),
        )

    @staticmethod
    def _message(row: sqlite3.Row) -> AgentMessage:
        """将 messages 表的数据库行转换为 AgentMessage 领域模型。"""
        return AgentMessage(
            message_id=str(row["message_id"]),
            task_id=str(row["task_id"]),
            target_agent_id=str(row["target_agent_id"]),
            type=str(row["type"]),
            payload=json.loads(row["payload_json"]),
            causation_id=row["causation_id"],
            correlation_id=str(row["correlation_id"]),
            priority=int(row["priority"]),
            status=MessageStatus(row["status"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _activity(row: sqlite3.Row) -> ActivityRequest:
        """将 activities 表的数据库行转换为 ActivityRequest 领域模型。"""
        return ActivityRequest(
            activity_id=str(row["activity_id"]),
            task_id=str(row["task_id"]),
            agent_id=str(row["agent_id"]),
            kind=row["kind"],
            request=json.loads(row["request_json"]),
            status=ActivityStatus(row["status"]),
            priority=int(row["priority"]),
            idempotency_key=str(row["idempotency_key"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _insert_message(
        connection: sqlite3.Connection,
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
        connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                message_id,
                task_id,
                target_agent_id,
                message_type,
                _json(payload),
                causation_id,
                correlation_id,
                priority,
                MessageStatus.PENDING,
                now,
            ),
        )
        return message_id

    @staticmethod
    def _insert_causal_event(
        connection: sqlite3.Connection,
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
        connection.execute(
            "INSERT INTO causal_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                task_id,
                agent_id,
                event_type,
                summary,
                _json(payload),
                causation_id,
                correlation_id,
                now,
            ),
        )
        return event_id
