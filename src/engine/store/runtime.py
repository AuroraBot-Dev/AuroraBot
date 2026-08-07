"""Task、Agent、消息与因果事件查询（Schema v9，RFC 0210）。"""

from __future__ import annotations

import json
from typing import Any

from src.contracts import AgentInstance, TaskState

from .base import RuntimeStoreBase, utc_now
from .status import (
    ACT_COMPLETED,
    ACT_ERROR,
    AGENT_TERMINAL,
    MSG_PENDING,
    TASK_ACTIVE,
)


class StoreRuntimeMixin(RuntimeStoreBase):
    """运行态只读查询与状态 CRUD。"""

    def get_task(self, task_id: str) -> TaskState | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return self._task(row) if row is not None else None

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            return self._agent(row) if row is not None else None

    def children(self, agent_id: str) -> tuple[AgentInstance, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agents WHERE parent_agent_id = ? ORDER BY created_at, agent_id", (agent_id,)
            ).fetchall()
            return tuple(self._agent(row) for row in rows)

    def tasks(self, *, active_only: bool = False) -> tuple[TaskState, ...]:
        query = "SELECT * FROM tasks"
        if active_only:
            query += f" WHERE status = {TASK_ACTIVE}"
        query += " ORDER BY started_at, task_id"
        with self.connect() as connection:
            return tuple(self._task(row) for row in connection.execute(query).fetchall())

    def agents(self, *, active_only: bool = False) -> tuple[AgentInstance, ...]:
        query = "SELECT * FROM agents"
        if active_only:
            query += f" WHERE status NOT IN {AGENT_TERMINAL}"
        query += " ORDER BY created_at, agent_id"
        with self.connect() as connection:
            return tuple(self._agent(row) for row in connection.execute(query).fetchall())

    def messages_for_agent(self, agent_id: str) -> tuple[dict[str, Any], ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE target_agent_id = ? ORDER BY created_at, message_id", (agent_id,)
            ).fetchall()
            return tuple(self._message(row).to_dict() for row in rows)

    def has_pending_child_reports(self, agent_id: str) -> bool:
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM messages WHERE target_agent_id = ? AND type IN ('child.completed', 'child.failed') "
                    f"AND status = {MSG_PENDING} LIMIT 1",
                    (agent_id,),
                ).fetchone()
            )

    def events_for_task(self, task_id: str) -> tuple[dict[str, Any], ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM causal_events WHERE task_id = ? ORDER BY created_at, event_id", (task_id,)
            ).fetchall()
            return tuple(
                {
                    "event_id": row["event_id"],
                    "task_id": row["task_id"],
                    "agent_id": row["agent_id"],
                    "type": row["type"],
                    "summary": row["summary"],
                    "payload": json.loads(row["payload_json"]),
                    "causation_id": row["causation_id"],
                    "correlation_id": row["correlation_id"],
                    "created_at": row["created_at"],
                }
                for row in rows
            )

    def recent_outputs(self, cursor: int = 0, *, limit: int = 64) -> tuple[dict[str, Any], ...]:
        """返回游标之后新增的模型输出文本，按活动行 ID 单调排序。

        kind 为 ``model`` 时取模型结果文本，为 ``error`` 时取失败信息；
        空文本的条目也返回，以便游标持续前进。
        """
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT a.rowid, a.activity_id, a.task_id, t.session_id, a.result_json, a.error, a.updated_at "
                "FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                f"WHERE a.kind = 'model' AND a.status IN ({ACT_COMPLETED}, {ACT_ERROR}) AND a.rowid > ? "
                "ORDER BY a.rowid LIMIT ?",
                (cursor, limit),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            kind = "error"
            text = str(row["error"]) if row["error"] else ""
            result = json.loads(row["result_json"]) if row["result_json"] else None
            if not row["error"] and isinstance(result, dict) and isinstance(result.get("text"), str):
                kind = "model"
                text = result["text"]
            items.append(
                {
                    "cursor": int(row["rowid"]),
                    "activity_id": str(row["activity_id"]),
                    "task_id": str(row["task_id"]),
                    "session_id": str(row["session_id"]),
                    "kind": kind,
                    "text": text,
                    "at": str(row["updated_at"]),
                }
            )
        return tuple(items)

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "inbox_events": int(connection.execute("SELECT count(*) FROM inbox_events").fetchone()[0]),
                "due_inbox_sessions": int(
                    connection.execute(
                        "SELECT count(DISTINCT session_id) FROM inbox_events "
                        "WHERE status IN ('PENDING', 'DEFERRED') AND available_at <= ?",
                        (utc_now(),),
                    ).fetchone()[0]
                ),
                "active_tasks": int(
                    connection.execute(f"SELECT count(*) FROM tasks WHERE status = {TASK_ACTIVE}").fetchone()[0]
                ),
                "active_agents": int(
                    connection.execute(f"SELECT count(*) FROM agents WHERE status NOT IN {AGENT_TERMINAL}").fetchone()[
                        0
                    ]
                ),
                "pending_messages": int(
                    connection.execute(f"SELECT count(*) FROM messages WHERE status = {MSG_PENDING}").fetchone()[0]
                ),
                "pending_activities": int(
                    connection.execute("SELECT count(*) FROM activities WHERE status = 'PENDING'").fetchone()[0]
                ),
                "pending_model_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'model' AND status = 'PENDING'"
                    ).fetchone()[0]
                ),
                "pending_tool_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'tool' AND status = 'PENDING'"
                    ).fetchone()[0]
                ),
            }
