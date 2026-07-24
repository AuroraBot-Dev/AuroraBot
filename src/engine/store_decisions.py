"""原子 Agent 决策提交、监督更新与 Task 终止。

apply_decision 是本模块的核心入口：在单一事务中执行已授权的 Agent 决策，
包括模型调用、工具请求、委托、完成、失败、等待等六种指令，
并同时写入邮箱出站消息、因果事件和状态更新。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.contracts.agent import (
    AgentInstance,
    AgentMessage,
    AgentStatus,
    ChildResult,
    MessageStatus,
    TaskStatus,
)
from src.engine.commands import (
    CompleteCommand,
    DelegateCommand,
    FailCommand,
    ModelCommand,
    ToolCommand,
    WaitCommand,
)
from src.engine.store_base import RuntimeStoreBase, _json, utc_now


class StoreDecisionsMixin(RuntimeStoreBase):
    """决策提交 Mixin：原子执行 Agent 决策，管理监督树和 Task 终止。"""

    def apply_decision(
        self,
        *,
        message: AgentMessage,
        agent: AgentInstance,
        command: ModelCommand | ToolCommand | DelegateCommand | CompleteCommand | WaitCommand | FailCommand,
        state_patch: dict[str, Any],
        limits: dict[str, int],
        priority: int,
    ) -> tuple[str, ...]:
        """在单一事务中原子执行一条已授权的 Agent 决策及所有出站写入。

        根据命令类型执行对应逻辑：
        - ModelCommand：检查模型调用预算，创建 PENDING model Activity
        - ToolCommand：检查工具调用预算，创建 PENDING tool Activity
        - DelegateCommand：检查监督限额（深度、子节点数等），创建子 Agent
        - WaitCommand：Agent 进入 WAITING_CHILDREN 状态
        - CompleteCommand：Agent 完成，通知父 Agent 或结束 Task
        - FailCommand：Agent 失败，通知父 Agent 或结束 Task

        所有命令统一处理 situation 认领、Agent 状态更新、消息完成和因果事件记录。
        返回本次决策创建的所有新实体 ID（子 Agent、邮箱消息、Activity）。
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
                raise RuntimeError("Agent message lease was lost")
            if agent_row is None or int(agent_row["revision"]) != agent.revision:
                raise RuntimeError("Agent revision conflict")
            if task_row is None or task_row["status"] != TaskStatus.ACTIVE:
                raise RuntimeError("Task is no longer active")
            state = json.loads(agent_row["state_json"])
            state.update(state_patch)
            status = AgentStatus.READY
            summary = command.summary

            if isinstance(command, ModelCommand):
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
                        "INSERT INTO activities VALUES (?, ?, ?, 'model', ?, 'PENDING', ?, ?, NULL, ?, ?, NULL, NULL)",
                        (
                            activity_id,
                            agent.task_id,
                            agent.agent_id,
                            _json(command.request),
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
                    status = AgentStatus.WAITING_MODEL
                    created.append(activity_id)

            elif isinstance(command, ToolCommand):
                # 检查工具调用预算，超出则终止 Task
                if int(task_row["tool_calls"]) >= int(task_row["max_tool_calls"]):
                    self._end_task(connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "tool_budget_exhausted", now)
                    status = AgentStatus.CANCELLED
                else:
                    # 创建 PENDING tool Activity，等待外部效果执行器处理
                    activity_id = str(uuid4())
                    request_id = str(uuid4())
                    request = {**command.request, "request_id": request_id}
                    connection.execute(
                        "INSERT INTO activities VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, NULL, ?, ?, NULL, NULL)",
                        (
                            activity_id,
                            agent.task_id,
                            agent.agent_id,
                            command.kind,
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
                    status = AgentStatus.WAITING_TOOL
                    created.append(activity_id)

            elif isinstance(command, DelegateCommand):
                requests = command.requests
                # 检查委托限额：深度、每 Agent 子节点数、每 Task 总 Agent 数、全局活跃 Agent 数
                current_count = int(
                    connection.execute("SELECT count(*) FROM agents WHERE task_id = ?", (agent.task_id,)).fetchone()[0]
                )
                active_count = int(
                    connection.execute(
                        "SELECT count(*) FROM agents WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')"
                    ).fetchone()[0]
                )
                child_count = int(
                    connection.execute(
                        "SELECT count(*) FROM agents WHERE parent_agent_id = ?", (agent.agent_id,)
                    ).fetchone()[0]
                )
                if (
                    agent.depth >= limits["max_depth"]
                    or child_count + len(requests) > limits["max_children_per_agent"]
                    or current_count + len(requests) > limits["max_agents_per_task"]
                    or active_count + len(requests) > limits["max_active_agents"]
                ):
                    raise PermissionError("Agent delegation limit exceeded")
                for request in requests:
                    child_id = str(uuid4())
                    instruction = str(request["instruction"])
                    # 创建子 Agent，depth + 1，初始状态为 READY
                    connection.execute(
                        "INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, 'READY', 0, '{}', ?, ?, ?)",
                        (
                            child_id,
                            agent.task_id,
                            agent.agent_id,
                            request["profile_id"],
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
                status = AgentStatus.WAITING_CHILDREN

            elif isinstance(command, WaitCommand):
                status = AgentStatus.WAITING_CHILDREN

            elif isinstance(command, CompleteCommand):
                status = AgentStatus.COMPLETED
                if agent.parent_agent_id is not None:
                    # 非根 Agent：向父 Agent 发送 child.completed 消息
                    result = ChildResult(
                        child_agent_id=agent.agent_id,
                        status="completed",
                        summary=summary,
                        artifacts=command.artifacts,
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
                    task_status = TaskStatus.SILENT if command.silent else TaskStatus.COMPLETED
                    self._end_task(connection, agent.task_id, task_status, summary, now)

            elif isinstance(command, FailCommand):
                status = AgentStatus.FAILED
                if agent.parent_agent_id is not None:
                    # 非根 Agent：向父 Agent 发送 child.failed 消息
                    result = ChildResult(
                        child_agent_id=agent.agent_id,
                        status="failed",
                        summary=summary,
                        artifacts=(),
                        error=command.error,
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

            else:
                raise ValueError(f"不支持的 Agent 指令 {command.kind}")

            # 认领决策中引用的所有情境（CAS 操作，仅当状态为 OPEN 且未过期）
            for situation_id in command.claims:
                claimed = connection.execute(
                    "UPDATE situations SET status = 'CLAIMED', claimed_by_agent_id = ?, updated_at = ? "
                    "WHERE situation_id = ? AND status = 'OPEN' AND expires_at > ?",
                    (agent.agent_id, now, situation_id, now),
                )
                if claimed.rowcount != 1:
                    raise PermissionError(f"情境不可用: {situation_id}")

            # 更新 Agent 状态（revision +1 实现乐观并发）、消息完成和因果事件
            connection.execute(
                "UPDATE agents SET status = ?, revision = revision + 1, state_json = ?, "
                "last_summary = ?, updated_at = ? "
                "WHERE agent_id = ?",
                (status, _json(state), summary, now, agent.agent_id),
            )
            connection.execute(
                "UPDATE mailbox SET status = 'COMPLETED', lease_until = NULL, completed_at = ? WHERE message_id = ?",
                (now, message.message_id),
            )
            connection.execute(
                "INSERT INTO causal_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    str(uuid4()),
                    agent.task_id,
                    agent.agent_id,
                    f"agent.{command.kind}",
                    summary,
                    _json(command.to_dict()),
                    message.message_id,
                    agent.task_id,
                    now,
                ),
            )
        return tuple(created)

    @staticmethod
    def _end_task(connection: sqlite3.Connection, task_id: str, status: TaskStatus, reason: str, now: str) -> None:
        """终止 Task：更新 Task 状态为终止态，级联取消所有非终态 Agent、消息和 Activity。"""
        connection.execute(
            "UPDATE tasks SET status = ?, termination_reason = ?, updated_at = ? WHERE task_id = ?",
            (status, reason, now, task_id),
        )
        connection.execute(
            "UPDATE agents SET status = 'CANCELLED', updated_at = ? WHERE task_id = ? "
            "AND status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')",
            (now, task_id),
        )
        connection.execute(
            "UPDATE mailbox SET status = 'ERROR', completed_at = ?, lease_until = NULL WHERE task_id = ? "
            "AND status IN ('PENDING', 'PROCESSING')",
            (now, task_id),
        )
        connection.execute(
            "UPDATE activities SET status = 'CANCELLED', updated_at = ?, lease_until = NULL WHERE task_id = ? "
            "AND status IN ('PENDING', 'PROCESSING')",
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
            rows = connection.execute("SELECT * FROM tasks WHERE status = 'ACTIVE'").fetchall()
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
