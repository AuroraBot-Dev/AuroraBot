"""原子 Agent 决策提交、监督更新与 Task 终止。

apply_decision 是本模块的核心入口：在单一事务中原子执行一条已授权的
AgentDecision（模型调用、工具请求、委托、完成、等待、失败六种转换），
并同时写入邮箱出站消息、因果事件和状态更新。

等待语义由数据库事实派生（RFC 0205）：非终态决策统一落到 READY 基态，
消息接纳由 claim_message 基于 activities/children 的存在性判断。
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

    LEASE_LOST = "Agent message lease was lost"
    REVISION_CONFLICT = "Agent revision conflict"
    TASK_NOT_ACTIVE = "Task is no longer active"
    DELEGATION_LIMIT = "Agent delegation limit exceeded"
    WAIT_WITHOUT_CHILDREN = "Agent cannot wait without active children"
    UNSUPPORTED_DECISION = "unsupported Agent decision"


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
    failure = decision.failure
    return failure if failure is not None else ""


class StoreDecisionsMixin(RuntimeStoreBase):
    """决策提交 Mixin：原子执行 Agent 决策，管理监督树和 Task 终止。"""

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
        - delegations：检查监督限额（深度、子节点数等），以 limits.worker_profile
          解析默认 child profile，创建子 Agent
        - wait_for_children：原子校验存在非终态 children 或 pending child reports
        - completion / failure：完成或失败，通知父 Agent 或结束 Task

        所有决策统一将 Agent 落回 READY 基态（终态除外）、完成消息、
        记录因果事件。返回本次决策创建的所有新实体 ID。
        """
        now = utc_now()
        created: list[str] = []
        with self.transaction() as connection:
            # 校验消息租约、Agent 版本和 Task 活跃性
            message_row = connection.execute(
                "SELECT * FROM mailbox WHERE message_id = ?", (message.message_id,)
            ).fetchone()
            agent_row = connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent.agent_id,)).fetchone()
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (agent.task_id,)).fetchone()
            if message_row is None or message_row["status"] != MessageStatus.PROCESSING:
                raise RuntimeError(_Msg.LEASE_LOST)
            if agent_row is None or int(agent_row["revision"]) != agent.revision:
                raise RuntimeError(_Msg.REVISION_CONFLICT)
            if task_row is None or task_row["status"] != TaskStatus.ACTIVE:
                raise RuntimeError(_Msg.TASK_NOT_ACTIVE)
            state = json.loads(agent_row["state_json"])
            state.update(state_patch)
            status = AgentStatus.READY
            summary = _decision_summary(decision)

            if decision.model_request is not None:
                # 检查模型调用预算，超出则终止 Task
                if int(task_row["model_calls"]) >= int(task_row["max_model_calls"]):
                    self._end_task(
                        connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "model_budget_exhausted", now
                    )
                    status = AgentStatus.CANCELLED
                else:
                    # 创建 PENDING model Activity，等待外部模型服务处理
                    activity_id = str(uuid4())
                    connection.execute(
                        "INSERT INTO activities VALUES (?, ?, ?, 'model', ?, "
                        f"{ACT_PENDING}, ?, ?, NULL, ?, ?, NULL, NULL)",
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
                # 检查工具调用预算，超出则终止 Task
                if int(task_row["tool_calls"]) >= int(task_row["max_tool_calls"]):
                    self._end_task(connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "tool_budget_exhausted", now)
                    status = AgentStatus.CANCELLED
                else:
                    # 创建 PENDING tool Activity；session_id 与 request_id 在事务内解析
                    activity_id = str(uuid4())
                    request_id = str(uuid4())
                    request = {
                        **decision.tool_request.to_dict(),
                        "request_id": request_id,
                        "session_id": str(task_row["session_id"]),
                    }
                    connection.execute(
                        f"INSERT INTO activities VALUES (?, ?, ?, ?, ?, {ACT_PENDING}, ?, ?, NULL, ?, ?, NULL, NULL)",
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
                # 检查委托限额：深度、每 Agent 子节点数、每 Task 总 Agent 数、全局活跃 Agent 数
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
                for instruction, child_profile in resolved:
                    child_id = str(uuid4())
                    # 创建子 Agent，depth + 1，初始状态为 READY
                    connection.execute(
                        f"INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, {AGENT_READY}, 0, '{{}}', ?, ?, ?)",
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
                    child_message = self._insert_message(
                        connection,
                        task_id=agent.task_id,
                        target_agent_id=child_id,
                        message_type="agent.assigned",
                        payload={"instruction": instruction, "parent_agent_id": agent.agent_id},
                        causation_id=message.message_id,
                        correlation_id=agent.task_id,
                        priority=priority,
                        now=now,
                    )
                    created.extend((child_id, child_message))

            elif decision.completion is not None:
                completion = decision.completion
                status = AgentStatus.COMPLETED
                if agent.parent_agent_id is not None:
                    # 非根 Agent：向父 Agent 发送 child.completed 消息
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
                    # 根 Agent 完成：结束整个 Task（silent 模式标记为 SILENT）
                    task_status = TaskStatus.SILENT if completion.silent else TaskStatus.COMPLETED
                    self._end_task(connection, agent.task_id, task_status, summary, now)

            elif decision.wait_for_children:
                # 原子校验等待前提：存在非终态 children 或 pending child reports
                if not self._has_active_children(connection, agent.agent_id):
                    raise ValueError(_Msg.WAIT_WITHOUT_CHILDREN)

            else:
                failure = decision.failure
                if failure is None:
                    raise ValueError(_Msg.UNSUPPORTED_DECISION)
                status = AgentStatus.FAILED
                if agent.parent_agent_id is not None:
                    # 非根 Agent：向父 Agent 发送 child.failed 消息
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

            # 更新 Agent 状态（revision +1 实现乐观并发）、消息完成和因果事件
            connection.execute(
                "UPDATE agents SET status = ?, revision = revision + 1, state_json = ?, "
                "last_summary = ?, updated_at = ? "
                "WHERE agent_id = ?",
                (status, _json(state), summary, now, agent.agent_id),
            )
            connection.execute(
                f"UPDATE mailbox SET status = {MSG_COMPLETED}, lease_until = NULL, completed_at = ? "
                "WHERE message_id = ?",
                (now, message.message_id),
            )
            self._insert_causal_event(
                connection,
                event_type=f"agent.{_decision_kind(decision)}",
                summary=summary,
                payload=decision.to_dict(),
                task_id=agent.task_id,
                agent_id=agent.agent_id,
                causation_id=message.message_id,
                correlation_id=agent.task_id,
                now=now,
            )
        return tuple(created)

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
                "SELECT 1 FROM mailbox WHERE target_agent_id = ? "
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
            f"UPDATE mailbox SET status = {MSG_ERROR}, completed_at = ?, lease_until = NULL WHERE task_id = ? "
            f"AND status IN ({MSG_PENDING}, {MSG_PROCESSING})",
            (now, task_id),
        )
        connection.execute(
            f"UPDATE activities SET status = {ACT_CANCELLED}, updated_at = ?, lease_until = NULL WHERE task_id = ? "
            f"AND status IN {ACT_ACTIVE}",
            (now, task_id),
        )

    def cancel_task(self, task_id: str, reason: str) -> None:
        """手动取消指定 Task。将其状态设为 CANCELLED 并级联终止所有相关实体。"""
        with self.transaction() as connection:
            self._end_task(connection, task_id, TaskStatus.CANCELLED, reason, utc_now())

    def expire_tasks(self) -> tuple[str, ...]:
        """检查并终止所有超时的活跃 Task。每个 pump 周期调用一次。"""
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
