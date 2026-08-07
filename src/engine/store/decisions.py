"""原子 Agent 决策提交、消息/活动队列与 Task 终止（Schema v9，RFC 0210）。

apply_decision 在单一事务中原子执行一条已授权的 AgentDecision（模型、
工具、委托、完成、等待、defer、discard、失败八种转换），并同时写入
消息、因果事件（轻量载荷）与状态更新。单进程 asyncio 独占：无租约、
无乐观锁，claim 退化为原子 UPDATE。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from src.contracts import (
    AgentDecision,
    AgentInstance,
    AgentMessage,
    AgentStatus,
    ChildResult,
    MessageStatus,
    TaskStatus,
)

from .base import RuntimeStoreBase, _json, utc_now
from .inbox import StoreInboxMixin
from .status import (
    ACT_ACTIVE,
    ACT_CANCELLED,
    ACT_PENDING,
    AGENT_CANCELLED,
    AGENT_READY,
    AGENT_TERMINAL,
    MSG_COMPLETED,
    MSG_ERROR,
    MSG_PENDING,
    MSG_PROCESSING,
    TASK_ACTIVE,
)


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    MESSAGE_NOT_CLAIMED = "message is not in processing state"
    TASK_NOT_ACTIVE = "Task is no longer active"
    DELEGATION_LIMIT = "Agent delegation limit exceeded"
    TRIAGE_CONTROL_DENIED = "defer/discard is only allowed for the entry triage Agent"
    WAIT_WITHOUT_CHILDREN = "Agent cannot wait without active children"
    UNSUPPORTED_DECISION = "unsupported Agent decision"
    ACTIVITY_ROW_MISSING = "activity row missing for {activity_id}"


def _decision_kind(decision: AgentDecision) -> str:
    """决策类型：用于因果事件类型 agent.{kind}。"""
    if decision.model_request is not None:
        return "model"
    if decision.tool_request is not None:
        return "tool"
    if decision.delegations:
        return "delegate"
    if decision.completion is not None:
        return "complete"
    if decision.wait_for_children:
        return "wait"
    if decision.defer_seconds is not None:
        return "defer"
    if decision.discard:
        return "discard"
    return "fail"


def _decision_summary(decision: AgentDecision) -> str:
    """决策摘要：写入 last_summary 与因果事件。"""
    if decision.model_request is not None:
        return "model.requested"
    if decision.tool_request is not None:
        return f"tool.requested:{decision.tool_request.capability}"
    if decision.delegations:
        return f"delegated {len(decision.delegations)} child Agent(s)"
    if decision.completion is not None:
        return decision.completion.summary
    if decision.wait_for_children:
        return "waiting for child Agents"
    if decision.defer_seconds is not None:
        return decision.summary or f"triage.defer:{decision.defer_seconds}"
    if decision.discard:
        return decision.summary or "triage.discard"
    failure = decision.failure
    return failure if failure is not None else ""


def _decision_payload(decision: AgentDecision) -> dict[str, Any]:
    """轻量因果载荷（RFC 0210）：只存审计摘要字段，不存完整请求。"""
    if decision.model_request is not None:
        return {
            "role": decision.model_request.role,
            "tool_names": [tool.name for tool in decision.model_request.tools],
        }
    if decision.tool_request is not None:
        return {"capability": decision.tool_request.capability}
    if decision.delegations:
        return {"count": len(decision.delegations), "memory_candidates": list(decision.memory_candidates)}
    if decision.completion is not None:
        return {"silent": decision.completion.silent}
    if decision.wait_for_children:
        return {}
    if decision.defer_seconds is not None:
        return {"defer_seconds": decision.defer_seconds}
    if decision.discard:
        return {}
    return {"error": decision.failure}


class StoreDecisionsMixin(StoreInboxMixin, RuntimeStoreBase):
    """决策提交 Mixin：原子执行 Agent 决策，管理消息/活动队列与 Task 终止。

    继承 StoreInboxMixin 使 settle_batch（批次结算）对 pyright 可见；
    组合顺序由 SQLiteRuntimeStore 的 MRO 保证。
    """

    def apply_decision(
        self,
        *,
        message: AgentMessage,
        agent: AgentInstance,
        decision: AgentDecision,
        state_patch: dict[str, Any],
        limits: dict[str, Any],
        priority: int,
    ) -> tuple[str, ...]:
        """在单一事务中原子执行一条已授权的 Agent 决策及所有出站写入。

        根据决策类型执行对应逻辑：
        - model_request：检查模型调用预算，创建 PENDING model Activity
        - tool_request：检查工具调用预算，在事务内解析 session_id，创建 PENDING tool Activity
        - delegations：检查监督限额，解析默认 child profile，创建子 Agent
        - wait_for_children：原子校验存在非终态 children 或 pending child reports
        - defer / discard：仅入口 triage agent，结算批次并终止 Task
        - completion / failure：完成或失败，通知父 Agent 或结束 Task

        返回本次决策创建的所有新实体 ID。
        """
        now = utc_now()
        created: list[str] = []
        with self.transaction() as connection:
            message_row = connection.execute(
                "SELECT * FROM messages WHERE message_id = ?", (message.message_id,)
            ).fetchone()
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (agent.task_id,)).fetchone()
            if message_row is None or message_row["status"] != MessageStatus.PROCESSING:
                raise RuntimeError(_Msg.MESSAGE_NOT_CLAIMED)
            if task_row is None or task_row["status"] != TaskStatus.ACTIVE:
                raise RuntimeError(_Msg.TASK_NOT_ACTIVE)
            state = json.loads(
                connection.execute("SELECT state_json FROM agents WHERE agent_id = ?", (agent.agent_id,)).fetchone()[
                    "state_json"
                ]
            )
            state.update(state_patch)
            status = AgentStatus.READY
            summary = _decision_summary(decision)

            if decision.model_request is not None:
                if int(task_row["model_calls"]) >= int(task_row["max_model_calls"]):
                    self._end_task(
                        connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "model_budget_exhausted", now
                    )
                    status = AgentStatus.CANCELLED
                else:
                    activity_id = str(uuid4())
                    connection.execute(
                        f"INSERT INTO activities VALUES (?, ?, ?, 'model', ?, {ACT_PENDING}, ?, ?, ?, ?, NULL, NULL)",
                        (
                            activity_id,
                            agent.task_id,
                            agent.agent_id,
                            _json(decision.model_request.to_dict()),
                            priority,
                            activity_id,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        "UPDATE tasks SET model_calls = model_calls + 1, updated_at = ? WHERE task_id = ?",
                        (now, agent.task_id),
                    )
                    created.append(activity_id)

            elif decision.tool_request is not None:
                if int(task_row["tool_calls"]) >= int(task_row["max_tool_calls"]):
                    self._end_task(connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "tool_budget_exhausted", now)
                    status = AgentStatus.CANCELLED
                else:
                    activity_id = str(uuid4())
                    request_id = str(uuid4())
                    request = {
                        **decision.tool_request.to_dict(),
                        "request_id": request_id,
                        "session_id": str(task_row["session_id"]),
                    }
                    connection.execute(
                        f"INSERT INTO activities VALUES (?, ?, ?, ?, ?, {ACT_PENDING}, ?, ?, ?, ?, NULL, NULL)",
                        (
                            activity_id,
                            agent.task_id,
                            agent.agent_id,
                            "tool",
                            _json(request),
                            priority,
                            request_id,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        "UPDATE tasks SET tool_calls = tool_calls + 1, updated_at = ? WHERE task_id = ?",
                        (now, agent.task_id),
                    )
                    created.append(activity_id)

            elif decision.delegations:
                worker_profile = str(limits["worker_profile"])
                resolved = [
                    (request.instruction, request.profile_id or worker_profile) for request in decision.delegations
                ]
                current_count = int(
                    connection.execute("SELECT count(*) FROM agents WHERE task_id = ?", (agent.task_id,)).fetchone()[0]
                )
                active_count = int(
                    connection.execute(f"SELECT count(*) FROM agents WHERE status NOT IN {AGENT_TERMINAL}").fetchone()[
                        0
                    ]
                )
                child_count = int(
                    connection.execute(
                        "SELECT count(*) FROM agents WHERE parent_agent_id = ?", (agent.agent_id,)
                    ).fetchone()[0]
                )
                if (
                    agent.depth >= limits["max_depth"]
                    or child_count + len(resolved) > limits["max_children_per_agent"]
                    or current_count + len(resolved) > limits["max_agents_per_task"]
                    or active_count + len(resolved) > limits["max_active_agents"]
                ):
                    raise PermissionError(_Msg.DELEGATION_LIMIT)
                batch_events = self._root_batch_events(state)
                for instruction, child_profile in resolved:
                    child_id = str(uuid4())
                    connection.execute(
                        f"INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, {AGENT_READY}, '{{}}', ?, ?, ?)",
                        (
                            child_id,
                            agent.task_id,
                            agent.agent_id,
                            child_profile,
                            agent.depth + 1,
                            instruction,
                            now,
                            now,
                            instruction,
                        ),
                    )
                    payload: dict[str, Any] = {"instruction": instruction, "parent_agent_id": agent.agent_id}
                    if batch_events is not None:
                        # 入口 agent 委派时，把有界批次投影交给子 Agent（RFC 0209）
                        payload["context_events"] = batch_events
                    child_message = self._insert_message(
                        connection,
                        task_id=agent.task_id,
                        target_agent_id=child_id,
                        message_type="agent.assigned",
                        payload=payload,
                        causation_id=message.message_id,
                        correlation_id=agent.task_id,
                        priority=priority,
                        now=now,
                    )
                    created.extend((child_id, child_message))
                if batch_events is not None:
                    self.settle_batch(connection, str(task_row["root_message_id"]), "delete", now)

            elif decision.defer_seconds is not None:
                self._require_triage_root(agent, task_row)
                self.settle_batch(connection, str(task_row["root_message_id"]), "defer", now, decision.defer_seconds)
                status = AgentStatus.COMPLETED
                self._end_task(connection, agent.task_id, TaskStatus.CANCELLED, "triage.defer", now)

            elif decision.discard:
                self._require_triage_root(agent, task_row)
                self.settle_batch(connection, str(task_row["root_message_id"]), "delete", now)
                status = AgentStatus.COMPLETED
                self._end_task(connection, agent.task_id, TaskStatus.CANCELLED, "triage.discard", now)

            elif decision.completion is not None:
                completion = decision.completion
                status = AgentStatus.COMPLETED
                if self._root_batch_events(state) is not None:
                    # 入口 agent 直接完成（未委派）：按 process 语义结算批次（RFC 0209）
                    self.settle_batch(connection, str(task_row["root_message_id"]), "delete", now)
                if agent.parent_agent_id is not None:
                    result = ChildResult(
                        child_agent_id=agent.agent_id,
                        status="completed",
                        summary=summary,
                        artifacts=completion.artifacts,
                        error=None,
                    )
                    child_message = self._insert_message(
                        connection,
                        task_id=agent.task_id,
                        target_agent_id=agent.parent_agent_id,
                        message_type="child.completed",
                        payload=result.to_dict(),
                        causation_id=message.message_id,
                        correlation_id=agent.task_id,
                        priority=priority,
                        now=now,
                    )
                    created.append(child_message)
                else:
                    task_status = TaskStatus.SILENT if completion.silent else TaskStatus.COMPLETED
                    self._end_task(connection, agent.task_id, task_status, summary, now)

            elif decision.wait_for_children:
                if not self._has_active_children(connection, agent.agent_id):
                    raise ValueError(_Msg.WAIT_WITHOUT_CHILDREN)

            else:
                failure = decision.failure
                if failure is None:
                    raise ValueError(_Msg.UNSUPPORTED_DECISION)
                status = AgentStatus.FAILED
                if self._root_batch_events(state) is not None:
                    # 入口 triage agent 失败：结算批次，避免 Inbox 残留（fail-open 已由 handler 兜底）
                    self.settle_batch(connection, str(task_row["root_message_id"]), "delete", now)
                if agent.parent_agent_id is not None:
                    result = ChildResult(
                        child_agent_id=agent.agent_id,
                        status="failed",
                        summary=summary,
                        artifacts=(),
                        error=failure,
                    )
                    child_message = self._insert_message(
                        connection,
                        task_id=agent.task_id,
                        target_agent_id=agent.parent_agent_id,
                        message_type="child.failed",
                        payload=result.to_dict(),
                        causation_id=message.message_id,
                        correlation_id=agent.task_id,
                        priority=priority,
                        now=now,
                    )
                    created.append(child_message)
                else:
                    self._end_task(connection, agent.task_id, TaskStatus.ERROR, summary, now)

            connection.execute(
                "UPDATE agents SET status = ?, state_json = ?, last_summary = ?, updated_at = ? WHERE agent_id = ?",
                (status, _json(state), summary, now, agent.agent_id),
            )
            connection.execute(
                f"UPDATE messages SET status = {MSG_COMPLETED}, completed_at = ? WHERE message_id = ?",
                (now, message.message_id),
            )
            self._insert_causal_event(
                connection,
                event_type=f"agent.{_decision_kind(decision)}",
                summary=summary,
                payload=_decision_payload(decision),
                task_id=agent.task_id,
                agent_id=agent.agent_id,
                causation_id=message.message_id,
                correlation_id=agent.task_id,
                now=now,
            )
        return tuple(created)

    # -- 消息与活动队列（无租约原子 claim）--------------------------------

    def claim_message(self) -> tuple[AgentMessage, AgentInstance, Any] | None:
        """原子领取一条可处理消息（含其 Agent 与 Task），单进程无竞争。"""
        with self.transaction() as connection:
            row = connection.execute(
                f"SELECT * FROM messages WHERE status = {MSG_PENDING} "
                "ORDER BY priority DESC, created_at, message_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                f"UPDATE messages SET status = {MSG_PROCESSING} WHERE message_id = ?", (row["message_id"],)
            )
            message = self._message(
                connection.execute("SELECT * FROM messages WHERE message_id = ?", (row["message_id"],)).fetchone()
            )
            agent_row = connection.execute(
                "SELECT * FROM agents WHERE agent_id = ?", (message.target_agent_id,)
            ).fetchone()
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (message.task_id,)).fetchone()
            if agent_row is None or task_row is None or task_row["status"] != TaskStatus.ACTIVE:
                connection.execute(
                    f"UPDATE messages SET status = {MSG_ERROR}, completed_at = ? WHERE message_id = ?",
                    (utc_now(), message.message_id),
                )
                return None
            return message, self._agent(agent_row), self._task(task_row)

    def fail_message(self, message_id: str, error: str) -> None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone()
            connection.execute(
                f"UPDATE messages SET status = {MSG_ERROR}, completed_at = ? WHERE message_id = ?",
                (utc_now(), message_id),
            )
            if row is not None:
                self._insert_causal_event(
                    connection,
                    event_type="message.failed",
                    summary=error,
                    payload={"message_id": message_id},
                    task_id=str(row["task_id"]),
                    agent_id=str(row["target_agent_id"]),
                    correlation_id=str(row["correlation_id"]),
                    now=utc_now(),
                )

    def claim_activities(self, kind: str, limit: int) -> tuple[Any, ...]:
        """原子领取指定类型的待处理活动，返回活动行对象。"""
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                f"WHERE a.kind = ? AND a.status = {ACT_PENDING} AND t.status = {TASK_ACTIVE} "
                "ORDER BY a.priority DESC, a.created_at LIMIT ?",
                (kind, limit),
            ).fetchall()
            result: list[Any] = []
            for row in rows:
                connection.execute(
                    "UPDATE activities SET status = 'PROCESSING', updated_at = ? WHERE activity_id = ?",
                    (utc_now(), row["activity_id"]),
                )
                updated = connection.execute(
                    "SELECT * FROM activities WHERE activity_id = ?", (row["activity_id"],)
                ).fetchone()
                if updated is None:
                    raise RuntimeError(_Msg.ACTIVITY_ROW_MISSING.format(activity_id=row["activity_id"]))
                result.append(updated)
            return tuple(result)

    def complete_model_activity(self, activity_id: str, result: dict[str, Any] | None, error: str | None) -> None:
        """完成模型活动：写入结果并投递 model.completed / model.failed 消息。"""
        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM activities WHERE activity_id = ? AND kind = 'model'", (activity_id,)
            ).fetchone()
            if row is None:
                return
            status = "COMPLETED" if error is None else "ERROR"
            connection.execute(
                "UPDATE activities SET status = ?, result_json = ?, error = ?, updated_at = ? WHERE activity_id = ?",
                (status, _json(result) if result is not None else None, error, now, activity_id),
            )
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
            if task_row is not None and task_row["status"] == TaskStatus.ACTIVE:
                payload: dict[str, Any] = (
                    {"activity_id": activity_id, "error": error}
                    if error is not None
                    else {"activity_id": activity_id, **(result or {})}
                )
                self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type="model.completed" if error is None else "model.failed",
                    payload=payload,
                    causation_id=activity_id,
                    correlation_id=str(row["task_id"]),
                    priority=int(row["priority"]),
                    now=now,
                )

    def claim_tool_activities(self, limit: int) -> tuple[Any, ...]:
        return self.claim_activities("tool", limit)

    def tool_recovery_activities(self) -> tuple[Any, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                f"WHERE a.kind = 'tool' AND a.status = 'PROCESSING' AND t.status = {TASK_ACTIVE}"
            ).fetchall()
            return tuple(rows)

    def consume_tool_receipt(
        self,
        *,
        request_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """消费工具回执 AMP（RFC 0211）：幂等投递 tool.{status} 消息给请求方 Agent。

        幂等键为 request_id：因果事件中已存在同类型回执则忽略（重放去重）。
        """
        now = utc_now()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT event_id FROM causal_events WHERE correlation_id = ? AND type = ?",
                (request_id, event_type),
            ).fetchone()
            if existing is not None:
                return False, None
            row = connection.execute(
                "SELECT * FROM activities WHERE idempotency_key = ? AND kind = 'tool'", (request_id,)
            ).fetchone()
            if row is None:
                return False, None
            status = "COMPLETED" if event_type == "tool.succeeded" else "ERROR"
            connection.execute(
                "UPDATE activities SET status = ?, result_json = ?, error = ?, updated_at = ? WHERE activity_id = ?",
                (
                    status,
                    _json(payload.get("result")) if payload.get("result") is not None else None,
                    payload.get("error"),
                    now,
                    row["activity_id"],
                ),
            )
            request = json.loads(row["request_json"])
            if event_type == "tool.succeeded" and request.get("complete_task") is True:
                # 工具成功后自动完成 Agent（RFC 0203 语义）：不投递 tool.succeeded 消息
                message_id = self._complete_agent_after_tool(connection, row, summary, now)
            else:
                message_id = self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type=event_type,
                    payload={**payload, "activity_id": row["activity_id"], "request": request},
                    causation_id=request_id,
                    correlation_id=request_id,
                    priority=int(row["priority"]),
                    now=now,
                )
            self._insert_causal_event(
                connection,
                event_type=event_type,
                summary=summary,
                payload={"request_id": request_id, "capability": payload.get("capability")},
                task_id=str(row["task_id"]),
                agent_id=str(row["agent_id"]),
                causation_id=request_id,
                correlation_id=request_id,
                now=now,
            )
            return True, message_id

    def _complete_agent_after_tool(
        self, connection: sqlite3.Connection, row: Any, summary: str, now: str
    ) -> str | None:
        """工具成功后自动完成 Agent。

        若为根 Agent，结束整个 Task；否则向父 Agent 发送 child.completed 消息。
        """
        agent = connection.execute("SELECT * FROM agents WHERE agent_id = ?", (row["agent_id"],)).fetchone()
        if agent is None:
            return None
        connection.execute(
            "UPDATE agents SET status = ?, last_summary = ?, updated_at = ? WHERE agent_id = ?",
            (AgentStatus.COMPLETED, summary, now, row["agent_id"]),
        )
        if agent["parent_agent_id"] is None:
            self._end_task(connection, str(row["task_id"]), TaskStatus.COMPLETED, summary, now)
            return None
        result = ChildResult(
            child_agent_id=str(row["agent_id"]),
            status="completed",
            summary=summary,
            artifacts=(),
            error=None,
        )
        return self._insert_message(
            connection,
            task_id=str(row["task_id"]),
            target_agent_id=str(agent["parent_agent_id"]),
            message_type="child.completed",
            payload=result.to_dict(),
            causation_id=str(row["activity_id"]),
            correlation_id=str(row["task_id"]),
            priority=int(row["priority"]),
            now=now,
        )

    def has_claimable_external_activity(self, limit: int) -> bool:
        with self.connect() as connection:
            processing = int(
                connection.execute(
                    "SELECT count(*) FROM activities WHERE kind = 'tool' AND status = 'PROCESSING'"
                ).fetchone()[0]
            )
            if processing >= limit:
                return False
            return bool(
                connection.execute(
                    "SELECT 1 FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                    f"WHERE a.kind = 'tool' AND a.status = {ACT_PENDING} AND t.status = {TASK_ACTIVE} LIMIT 1"
                ).fetchone()
            )

    def has_recoverable_tool(self) -> bool:
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                    "WHERE a.kind = 'tool' AND a.status = 'PROCESSING' AND t.status = "
                    f"{TASK_ACTIVE} LIMIT 1"
                ).fetchone()
            )

    # -- Task 终止与预算 -----------------------------------------------

    def cancel_task(self, task_id: str, reason: str) -> None:
        with self.transaction() as connection:
            self._end_task(connection, task_id, TaskStatus.CANCELLED, reason, utc_now())

    def expire_tasks(self) -> tuple[str, ...]:
        """检查并终止所有超时的活跃 Task（duration 预算）。"""
        now_dt = datetime.now(UTC)
        expired: list[str] = []
        with self.transaction() as connection:
            rows = connection.execute(f"SELECT * FROM tasks WHERE status = {TASK_ACTIVE}").fetchall()
            for row in rows:
                if (now_dt - datetime.fromisoformat(row["started_at"])).total_seconds() <= row["max_duration_seconds"]:
                    continue
                self._end_task(
                    connection,
                    str(row["task_id"]),
                    TaskStatus.BUDGET_EXHAUSTED,
                    "duration_budget_exhausted",
                    now_dt.isoformat(),
                )
                expired.append(str(row["task_id"]))
        return tuple(expired)

    # -- 内部辅助 -------------------------------------------------------

    @staticmethod
    def _root_batch_events(state: dict[str, Any]) -> list[Any] | None:
        """入口 agent 状态中的批次投影；仅 triage 创建的根 agent 携带。"""
        events = state.get("batch_events")
        return events if isinstance(events, list) else None

    @staticmethod
    def _require_triage_root(agent: AgentInstance, task_row: Any) -> None:
        """defer/discard 只允许入口 triage agent 发出（RFC 0209）。"""
        if agent.agent_id != str(task_row["root_agent_id"]):
            raise PermissionError(_Msg.TRIAGE_CONTROL_DENIED)

    @staticmethod
    def _has_active_children(connection: sqlite3.Connection, agent_id: str) -> bool:
        """派生等待前提：非终态 children 或 pending child reports。"""
        if (
            connection.execute(
                f"SELECT 1 FROM agents WHERE parent_agent_id = ? AND status NOT IN {AGENT_TERMINAL} LIMIT 1",
                (agent_id,),
            ).fetchone()
            is not None
        ):
            return True
        return (
            connection.execute(
                "SELECT 1 FROM messages WHERE target_agent_id = ? "
                "AND type IN ('child.completed', 'child.failed') "
                f"AND status = {MSG_PENDING} LIMIT 1",
                (agent_id,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _end_task(connection: sqlite3.Connection, task_id: str, status: TaskStatus, reason: str, now: str) -> None:
        """终止 Task：更新 Task 状态为终止态，级联取消所有非终态 Agent、消息和 Activity。"""
        connection.execute(
            "UPDATE tasks SET status = ?, termination_reason = ?, updated_at = ? WHERE task_id = ?",
            (status, reason, now, task_id),
        )
        connection.execute(
            f"UPDATE agents SET status = {AGENT_CANCELLED}, updated_at = ? WHERE task_id = ? "
            f"AND status NOT IN {AGENT_TERMINAL}",
            (now, task_id),
        )
        connection.execute(
            f"UPDATE messages SET status = {MSG_ERROR}, completed_at = ? WHERE task_id = ? "
            f"AND status IN ({MSG_PENDING}, {MSG_PROCESSING})",
            (now, task_id),
        )
        connection.execute(
            f"UPDATE activities SET status = {ACT_CANCELLED}, updated_at = ? WHERE task_id = ? "
            f"AND status IN {ACT_ACTIVE}",
            (now, task_id),
        )
