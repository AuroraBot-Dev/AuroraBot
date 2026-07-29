"""工具回执处理与 Agent 邮箱消息租赁。

Triage 前的 AMP 摄入与 admitted Task 创建位于 store/triage.py：
- complete_tool_activity：消费工具回执，推导事件前后因果
- claim_message：按 Agent 状态匹配邮箱消息供处理
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.contracts.agent import (
    ActivityStatus,
    AgentInstance,
    AgentMessage,
    TaskState,
    TaskStatus,
)

from .base import RuntimeStoreBase, _json, utc_now


class StoreIngressMixin(RuntimeStoreBase):
    """入口处理 Mixin：Task 创建、工具回执消费与邮箱消息租赁。"""

    def complete_tool_activity(
        self,
        *,
        external_message_id: str,
        request_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """消费工具回执一次，授权来自已持久化请求，支持幂等。

        返回 (bool, str | None)：布尔值区分已知的延迟/重复回执与无关外部事件。
        无关外部事件由调用者拒绝，不会进入 Agent mailbox。
        若工具请求标记 complete_task=True，则自动完成该 Agent。
        """
        now = utc_now()
        with self.transaction() as connection:
            # 外部事件幂等：同一 external_message_id 只消费一次
            if connection.execute(
                "SELECT 1 FROM causal_events WHERE external_message_id = ?", (external_message_id,)
            ).fetchone():
                return True, None
            # 通过 idempotency_key 关联原始 Activity 请求
            row = connection.execute(
                "SELECT a.*, t.status AS task_status FROM activities a "
                "JOIN tasks t ON t.task_id = a.task_id "
                "WHERE a.idempotency_key = ? AND a.kind = 'tool'",
                (request_id,),
            ).fetchone()
            if row is None:
                return False, None
            request = json.loads(row["request_json"])
            capability = payload.get("capability")
            if not isinstance(capability, str) or capability != request.get("capability"):
                return False, None
            if row["status"] != ActivityStatus.PROCESSING or row["task_status"] != TaskStatus.ACTIVE:
                # 延迟或重复回执：记录因果事件但不重复处理
                connection.execute(
                    "INSERT INTO causal_events VALUES (?, ?, ?, 'tool.receipt_ignored', ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        row["task_id"],
                        row["agent_id"],
                        f"Ignored late or duplicate receipt for {capability}",
                        _json(payload),
                        row["activity_id"],
                        row["task_id"],
                        external_message_id,
                        now,
                    ),
                )
                return True, None
            succeeded = event_type == "tool.succeeded"
            status = ActivityStatus.COMPLETED if succeeded else ActivityStatus.ERROR
            connection.execute(
                "UPDATE activities SET status = ?, result_json = ?, error = ?, lease_until = NULL, updated_at = ? "
                "WHERE activity_id = ?",
                (
                    status,
                    _json(payload.get("result")) if succeeded else None,
                    payload.get("error") if not succeeded else None,
                    now,
                    row["activity_id"],
                ),
            )
            message_id = None
            if succeeded and request.get("complete_task") is True:
                message_id = self._complete_agent_after_tool(connection, row, summary, now)
            else:
                message_payload = {**payload, "activity_id": row["activity_id"], "request": request}
                message_id = self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type=event_type,
                    payload=message_payload,
                    causation_id=str(row["activity_id"]),
                    correlation_id=str(row["task_id"]),
                    priority=int(row["priority"]),
                    now=now,
                )
            connection.execute(
                "INSERT INTO causal_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    row["task_id"],
                    row["agent_id"],
                    event_type,
                    summary,
                    _json(payload),
                    row["activity_id"],
                    row["task_id"],
                    external_message_id,
                    now,
                ),
            )
            return True, message_id

    def _complete_agent_after_tool(self, connection: Any, row: Any, summary: str, now: str) -> str | None:
        """工具成功后自动完成 Agent。

        若为根 Agent，结束整个 Task；否则向父 Agent 发送 child.completed 消息。
        """
        agent = connection.execute("SELECT * FROM agents WHERE agent_id = ?", (row["agent_id"],)).fetchone()
        assert agent is not None
        connection.execute(
            "UPDATE agents SET status = 'COMPLETED', last_summary = ?, updated_at = ? WHERE agent_id = ?",
            (summary, now, row["agent_id"]),
        )
        parent = agent["parent_agent_id"]
        if parent is None:
            self._end_task(connection, str(row["task_id"]), TaskStatus.COMPLETED, "tool_succeeded", now)
            return None
        return self._insert_message(
            connection,
            task_id=str(row["task_id"]),
            target_agent_id=str(parent),
            message_type="child.completed",
            payload={
                "child_agent_id": row["agent_id"],
                "status": "completed",
                "summary": summary,
                "artifacts": [],
                "error": None,
            },
            causation_id=str(row["activity_id"]),
            correlation_id=str(row["task_id"]),
            priority=int(row["priority"]),
            now=now,
        )

    def claim_message(self, lease_seconds: float) -> tuple[AgentMessage, AgentInstance, TaskState] | None:
        """领取下一条待处理消息并设置租约。

        先重置所有过期的 PROCESSING 消息为 PENDING，再按以下规则查找：
        - 仅匹配 ACTIVE Task 下的 READY Agent 或状态与消息类型一致的等待中 Agent
        - WAITING_MODEL 仅接收 model.* 消息
        - WAITING_TOOL 仅接收 tool.* 消息
        - WAITING_CHILDREN 仅接收 child.* 消息
        - 同一 Agent 不能同时有 PROCESSING 消息（邮箱租约即执行锁）
        按优先级降序、创建时间升序排列，返回 (消息, Agent, Task) 三元组。
        """
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE mailbox SET status = 'PENDING', lease_until = NULL WHERE status = 'PROCESSING' "
                "AND lease_until < ?",
                (now,),
            )
            row = connection.execute(
                "SELECT m.* FROM mailbox m JOIN tasks t ON t.task_id = m.task_id "
                "JOIN agents a ON a.agent_id = m.target_agent_id "
                "WHERE m.status = 'PENDING' AND m.available_at <= ? AND t.status = 'ACTIVE' "
                "AND NOT EXISTS (SELECT 1 FROM mailbox busy WHERE busy.target_agent_id = a.agent_id "
                "AND busy.status = 'PROCESSING') "
                "AND ((a.status = 'READY') "
                "OR (a.status = 'WAITING_MODEL' AND m.type IN ('model.completed', 'model.failed')) "
                "OR (a.status = 'WAITING_TOOL' AND m.type IN ("
                "'tool.succeeded', 'tool.failed', 'tool.unknown')) "
                "OR (a.status = 'WAITING_CHILDREN' AND m.type IN ('child.completed', 'child.failed'))) "
                "ORDER BY m.priority DESC, m.created_at, m.message_id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                "UPDATE mailbox SET status = 'PROCESSING', lease_until = ?, attempts = attempts + 1 "
                "WHERE message_id = ? AND status = 'PENDING'",
                (lease, row["message_id"]),
            )
            if updated.rowcount != 1:
                return None
            # 邮箱租约是逐 Agent 的执行锁。保留 WAITING_* 语义状态可防止无关唤醒。
            message_row = connection.execute(
                "SELECT * FROM mailbox WHERE message_id = ?", (row["message_id"],)
            ).fetchone()
            agent_row = connection.execute(
                "SELECT * FROM agents WHERE agent_id = ?", (row["target_agent_id"],)
            ).fetchone()
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
            assert message_row is not None and agent_row is not None and task_row is not None
            return self._message(message_row), self._agent(agent_row), self._task(task_row)

    def fail_message(self, message_id: str, agent_id: str, error: str) -> None:
        """将消息标记为错误并标记对应 Agent 为失败。仅在极端恢复场景使用。"""
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE mailbox SET status = 'ERROR', lease_until = NULL, completed_at = ? WHERE message_id = ?",
                (now, message_id),
            )
            connection.execute(
                "UPDATE agents SET status = 'FAILED', last_summary = ?, updated_at = ? WHERE agent_id = ?",
                (error, now, agent_id),
            )
