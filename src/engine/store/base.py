"""SQLite 连接管理、Schema 迁移与行数据转换，供所有 Store Mixin 共享。

提供事务管理、初始化迁移、中断恢复以及 Task/Agent/Message/Activity 的行映射。
所有写操作均需通过 transaction() 上下文管理器执行。
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

from src.contracts.agent import (
    ActivityRequest,
    ActivityStatus,
    AgentInstance,
    AgentMessage,
    AgentStatus,
    MessageStatus,
    TaskState,
    TaskStatus,
)
from src.utils.time import utc_now

from .schema import _ACTIVE_ACTIVITY_INDEX, _ACTIVITIES_V5, _SCHEMA, _SCHEMA_VERSION

_AUTO_VACUUM_INCREMENTAL = 2


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    UNSUPPORTED_SCHEMA = "不支持的 Agent 运行时数据库 Schema 版本"


def _json(value: object) -> str:
    """将 Python 对象序列化为紧凑 JSON 字符串，用于统一所有 JSON 列的存储格式。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class RuntimeStoreBase:
    """事务型持久化仓库基类。调用者将模型和平台 I/O 置于事务外部。

    所有写操作通过 transaction() 上下文管理器执行，自动 BEGIN IMMEDIATE/commit/rollback。
    行映射方法 _task/_agent/_message/_activity 将 sqlite3.Row 转换为领域数据类。
    """

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
        """初始化运行时数据库：创建目录、启用 WAL、执行 Schema 和渐进迁移。

        迁移策略：检查 schema_meta.version，按需执行 ALTER TABLE 添加列、
        统一旧的 effect/publication 语义为 tool，然后重置版本号。
        最后调用 recover_interrupted 重置所有 PROCESSING 状态。
        """
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA journal_size_limit = 1048576")
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
            connection.executescript(_SCHEMA)
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (_SCHEMA_VERSION,))
            elif int(row["version"]) not in {1, 2, 3, 4, 5, _SCHEMA_VERSION}:
                raise RuntimeError(_Msg.UNSUPPORTED_SCHEMA)
            version = int(row["version"]) if row is not None else _SCHEMA_VERSION
            if version < _SCHEMA_VERSION:
                task_columns = {str(item["name"]) for item in connection.execute("PRAGMA table_info(tasks)")}
                if "audience_ref" not in task_columns:
                    connection.execute("ALTER TABLE tasks ADD COLUMN audience_ref TEXT NOT NULL DEFAULT 'global'")
                situation_columns = {str(item["name"]) for item in connection.execute("PRAGMA table_info(situations)")}
                if "audience_ref" not in situation_columns:
                    connection.execute("ALTER TABLE situations ADD COLUMN audience_ref TEXT NOT NULL DEFAULT 'global'")
                activity_sql = str(
                    connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'activities'"
                    ).fetchone()["sql"]
                )
                if "'tool'" not in activity_sql:
                    connection.executescript(_ACTIVITIES_V5)
                connection.execute("UPDATE agents SET status = 'WAITING_TOOL' WHERE status = 'WAITING_EFFECT'")
                connection.execute(
                    "UPDATE mailbox SET type = CASE type "
                    "WHEN 'effect.succeeded' THEN 'tool.succeeded' "
                    "WHEN 'effect.failed' THEN 'tool.failed' "
                    "WHEN 'effect.delivery_unknown' THEN 'tool.unknown' "
                    "WHEN 'effect.unknown' THEN 'tool.unknown' "
                    "WHEN 'publication.succeeded' THEN 'tool.succeeded' "
                    "WHEN 'publication.failed' THEN 'tool.failed' "
                    "WHEN 'publication.delivery_unknown' THEN 'tool.unknown' "
                    "WHEN 'publication.unknown' THEN 'tool.unknown' "
                    "ELSE type END"
                )
            connection.execute(_ACTIVE_ACTIVITY_INDEX)
            connection.execute("UPDATE schema_meta SET version = ?", (_SCHEMA_VERSION,))
            connection.commit()
            if (
                version < _SCHEMA_VERSION
                and int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]) != _AUTO_VACUUM_INCREMENTAL
            ):
                connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
                connection.execute("VACUUM")
        self.recover_interrupted()

    def recover_interrupted(self) -> None:
        """恢复上次异常退出遗留的 PROCESSING 状态。

        将 PROCESSING 邮箱消息重置为 PENDING，将遗留的 RUNNING Agent 重置为 READY，
        并把中断的 model Activity 和旧版 effect Activity 标记为 ERROR 并通知相关 Agent。
        工具 Activity 仅清除租约，允许后续恢复。
        """
        now = utc_now()
        with self.transaction() as connection:
            connection.execute("UPDATE mailbox SET status = 'PENDING', lease_until = NULL WHERE status = 'PROCESSING'")
            # RUNNING 仅存在于 v2 之前的存储；邮箱租赁是当前锁机制
            connection.execute(
                "UPDATE agents SET status = 'READY', updated_at = ? WHERE status = 'RUNNING'",
                (now,),
            )
            interrupted = connection.execute(
                "SELECT * FROM activities WHERE "
                "(status = 'PROCESSING' AND kind = 'model') OR "
                "(status IN ('PENDING', 'PROCESSING') AND json_extract(request_json, '$.legacy_kind') IS NOT NULL)"
            ).fetchall()
            for row in interrupted:
                connection.execute(
                    "UPDATE activities SET status = 'ERROR', lease_until = NULL, error = ?, updated_at = ? "
                    "WHERE activity_id = ?",
                    ("interrupted_by_restart", now, row["activity_id"]),
                )
                self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type="model.failed" if row["kind"] == "model" else "tool.unknown",
                    payload={
                        "activity_id": row["activity_id"],
                        "error": "interrupted_by_restart",
                        "request": json.loads(row["request_json"]),
                    },
                    causation_id=str(row["activity_id"]),
                    correlation_id=str(row["task_id"]),
                    priority=int(row["priority"]),
                    now=now,
                )
            connection.execute(
                "UPDATE activities SET lease_until = NULL, updated_at = ? "
                "WHERE status = 'PROCESSING' AND kind = 'tool'",
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
            revision=int(row["revision"]),
            state=json.loads(row["state_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_summary=str(row["last_summary"]),
        )

    @staticmethod
    def _message(row: sqlite3.Row) -> AgentMessage:
        """将 mailbox 表的数据库行转换为 AgentMessage 领域模型。"""
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
            available_at=str(row["available_at"]),
            lease_until=row["lease_until"],
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
            lease_until=row["lease_until"],
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
            "INSERT INTO mailbox VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, NULL)",
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
                now,
            ),
        )
        return message_id

    @staticmethod
    def _end_task(connection: sqlite3.Connection, task_id: str, status: TaskStatus, reason: str, now: str) -> None:
        raise NotImplementedError

    def get_task(self, task_id: str) -> TaskState | None:
        raise NotImplementedError
