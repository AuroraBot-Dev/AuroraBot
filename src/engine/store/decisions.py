"""原子 Agent 决策提交、消息/活动队列与 Task 终止（Schema v10，SQLAlchemy ORM 实现）。

apply_decision 在单一事务中原子执行一条已授权的 AgentDecision（模型、
工具、委托、完成、等待、defer、discard、失败八种转换），并同时写入
消息、因果事件（轻量载荷）与状态更新。单进程 asyncio 独占：无租约、
无乐观锁，claim 退化为原子 UPDATE。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from src.contracts import (
    AgentDecision,
    AgentInstance,
    AgentMessage,
    AgentStatus,
    ChildResult,
    MessageStatus,
    TaskStatus,
    TriageLimits,
)

from .base import RuntimeStoreBase, _json, _loads, utc_now
from .inbox import StoreInboxMixin
from .models import (
    ACT_ACTIVE,
    ACT_CANCELLED,
    ACT_COMPLETED,
    ACT_ERROR,
    ACT_PENDING,
    ACT_PROCESSING,
    ACT_SUPERSEDED,
    AGENT_CANCELLED,
    AGENT_TERMINAL,
    INBOX_PENDING,
    MSG_COMPLETED,
    MSG_ERROR,
    MSG_PENDING,
    MSG_PROCESSING,
    TASK_ACTIVE,
    ActivityRow,
    AgentRow,
    CausalEventRow,
    InboxEventRow,
    MessageRow,
    OutputPublicationRow,
    SessionLaneRow,
    TaskRow,
)


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    MESSAGE_NOT_CLAIMED = "message is not in processing state"
    TASK_NOT_ACTIVE = "Task is no longer active"
    AGENT_ROW_MISSING = "agent row missing for {agent_id}"
    DELEGATION_LIMIT = "Agent delegation limit exceeded"
    TRIAGE_CONTROL_DENIED = "defer/discard is only allowed for the entry triage Agent"
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
    """轻量因果载荷：只存审计摘要字段，不存完整请求。"""
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
        with self.session() as session:
            message_row = session.scalar(select(MessageRow).where(MessageRow.message_id == message.message_id))
            task_row = session.scalar(select(TaskRow).where(TaskRow.task_id == agent.task_id))
            if message_row is None or message_row.status != MessageStatus.PROCESSING:
                raise RuntimeError(_Msg.MESSAGE_NOT_CLAIMED)
            if task_row is None or task_row.status != TaskStatus.ACTIVE:
                raise RuntimeError(_Msg.TASK_NOT_ACTIVE)
            generation_revision = 0
            if not task_row.autonomous:
                lane = session.get(SessionLaneRow, str(task_row.session_id))
                if lane is None or lane.active_task_id != task_row.task_id:
                    raise RuntimeError(_Msg.TASK_NOT_ACTIVE)
                generation_revision = int(lane.generation_revision)
            agent_row = session.scalar(select(AgentRow).where(AgentRow.agent_id == agent.agent_id))
            if agent_row is None:
                raise RuntimeError(_Msg.AGENT_ROW_MISSING.format(agent_id=agent.agent_id))
            state = _loads(agent_row.state_json)
            state.update(state_patch)
            status = AgentStatus.READY
            summary = _decision_summary(decision)

            if decision.model_request is not None:
                if task_row.model_calls >= task_row.max_model_calls:
                    self._end_task(session, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "model_budget_exhausted", now)
                    status = AgentStatus.CANCELLED
                else:
                    activity_id = str(uuid4())
                    session.add(
                        ActivityRow(
                            activity_id=activity_id,
                            task_id=agent.task_id,
                            agent_id=agent.agent_id,
                            kind="model",
                            request_json=_json(decision.model_request.to_dict()),
                            status=ACT_PENDING,
                            priority=priority,
                            idempotency_key=activity_id,
                            created_at=now,
                            updated_at=now,
                            generation_revision=generation_revision,
                            publishable=0,
                        )
                    )
                    task_row.model_calls += 1
                    task_row.updated_at = now
                    created.append(activity_id)

            elif decision.tool_request is not None:
                if task_row.tool_calls >= task_row.max_tool_calls:
                    self._end_task(session, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "tool_budget_exhausted", now)
                    status = AgentStatus.CANCELLED
                else:
                    activity_id = str(uuid4())
                    request_id = str(uuid4())
                    request = {
                        **decision.tool_request.to_dict(),
                        "request_id": request_id,
                        "session_id": str(task_row.session_id),
                    }
                    session.add(
                        ActivityRow(
                            activity_id=activity_id,
                            task_id=agent.task_id,
                            agent_id=agent.agent_id,
                            kind="tool",
                            request_json=_json(request),
                            status=ACT_PENDING,
                            priority=priority,
                            idempotency_key=request_id,
                            created_at=now,
                            updated_at=now,
                            generation_revision=generation_revision,
                            publishable=0,
                        )
                    )
                    task_row.tool_calls += 1
                    task_row.updated_at = now
                    created.append(activity_id)

            elif decision.delegations:
                worker_profile = str(limits["worker_profile"])
                resolved = [
                    (request.instruction, request.profile_id or worker_profile) for request in decision.delegations
                ]
                current_count = (
                    session.scalar(select(func.count()).select_from(AgentRow).where(AgentRow.task_id == agent.task_id))
                    or 0
                )
                active_count = (
                    session.scalar(
                        select(func.count()).select_from(AgentRow).where(AgentRow.status.not_in(AGENT_TERMINAL))
                    )
                    or 0
                )
                child_count = (
                    session.scalar(
                        select(func.count()).select_from(AgentRow).where(AgentRow.parent_agent_id == agent.agent_id)
                    )
                    or 0
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
                    session.add(
                        AgentRow(
                            agent_id=child_id,
                            task_id=agent.task_id,
                            parent_agent_id=agent.agent_id,
                            profile_id=child_profile,
                            depth=agent.depth + 1,
                            assignment=instruction,
                            status=AgentStatus.READY,
                            state_json="{}",
                            created_at=now,
                            updated_at=now,
                            last_summary=instruction,
                        )
                    )
                    payload: dict[str, Any] = {"instruction": instruction, "parent_agent_id": agent.agent_id}
                    if batch_events is not None:
                        # 入口 agent 委派时，把有界批次投影交给子 Agent
                        payload["context_events"] = batch_events
                    child_message = self._insert_message(
                        session,
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
            elif decision.defer_seconds is not None:
                self._require_triage_root(agent, task_row)
                self.settle_batch(session, task_row.root_message_id, "defer", now, decision.defer_seconds)
                status = AgentStatus.COMPLETED
                self._end_task(session, agent.task_id, TaskStatus.CANCELLED, "triage.defer", now)

            elif decision.discard:
                self._require_triage_root(agent, task_row)
                self.settle_batch(session, task_row.root_message_id, "delete", now)
                status = AgentStatus.COMPLETED
                self._end_task(session, agent.task_id, TaskStatus.CANCELLED, "triage.discard", now)

            elif decision.completion is not None:
                completion = decision.completion
                status = AgentStatus.COMPLETED
                if not completion.silent:
                    self._mark_model_publication(session, message)
                if self._root_batch_events(state) is not None:
                    # 入口 agent 直接完成（未委派）：按 process 语义结算批次
                    self.settle_batch(session, task_row.root_message_id, "delete", now)
                if agent.parent_agent_id is not None:
                    created.append(
                        self._notify_parent(
                            session,
                            agent,
                            message,
                            status="completed",
                            summary=summary,
                            artifacts=completion.artifacts,
                            priority=priority,
                            now=now,
                        )
                    )
                else:
                    task_status = TaskStatus.SILENT if completion.silent else TaskStatus.COMPLETED
                    self._end_task(session, agent.task_id, task_status, summary, now)

            elif decision.wait_for_children:
                if not self._has_active_children(session, agent.agent_id):
                    raise ValueError(_Msg.WAIT_WITHOUT_CHILDREN)

            else:
                failure = decision.failure
                if failure is None:
                    raise ValueError(_Msg.UNSUPPORTED_DECISION)
                status = AgentStatus.FAILED
                self._mark_model_publication(session, message)
                if self._root_batch_events(state) is not None:
                    # 入口 triage agent 失败：结算批次，避免 Inbox 残留（fail-open 已由 handler 兜底）
                    self.settle_batch(session, task_row.root_message_id, "delete", now)
                if agent.parent_agent_id is not None:
                    created.append(
                        self._notify_parent(
                            session,
                            agent,
                            message,
                            status="failed",
                            summary=summary,
                            error=failure,
                            priority=priority,
                            now=now,
                        )
                    )
                else:
                    self._end_task(session, agent.task_id, TaskStatus.ERROR, summary, now)

            agent_row.status = status
            agent_row.state_json = _json(state)
            agent_row.last_summary = summary
            agent_row.updated_at = now
            message_row.status = MSG_COMPLETED
            message_row.completed_at = now
            self._insert_causal_event(
                session,
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

    # === 消息与活动队列（无租约原子 claim） ===

    @staticmethod
    def _mark_model_publication(session: Session, message: AgentMessage) -> None:
        if message.type not in {"model.completed", "model.failed"}:
            return
        activity_id = message.payload.get("activity_id")
        if isinstance(activity_id, str):
            session.execute(
                update(ActivityRow)
                .where(ActivityRow.activity_id == activity_id, ActivityRow.status.in_((ACT_COMPLETED, ACT_ERROR)))
                .values(publishable=1)
            )

    def supersede_session_generation(self, amp: Any, limits: TriageLimits) -> tuple[str, ...]:
        """高优先级 AMP 有界取代同会话未提交 generation，返回需取消的模型 Activity。"""
        if not _requests_interrupt(amp):
            return ()
        now = utc_now()
        now_dt = datetime.fromisoformat(now)
        with self.session() as session:
            lane = session.get(SessionLaneRow, amp.payload.session_id)
            if lane is None or lane.active_task_id is None or lane.interrupt_count >= limits.max_interrupts:
                return ()
            task_row = session.get(TaskRow, lane.active_task_id)
            if task_row is None or task_row.status != TASK_ACTIVE or task_row.autonomous:
                return ()
            started = datetime.fromisoformat(lane.generation_started_at or task_row.started_at)
            if (now_dt - started).total_seconds() >= limits.max_generation_seconds:
                return ()
            processing_tool = session.scalar(
                select(ActivityRow.activity_id)
                .where(
                    ActivityRow.task_id == task_row.task_id,
                    ActivityRow.kind == "tool",
                    ActivityRow.status == ACT_PROCESSING,
                )
                .limit(1)
            )
            if processing_tool is not None:
                return ()
            active_models = tuple(
                session.scalars(
                    select(ActivityRow).where(
                        ActivityRow.task_id == task_row.task_id,
                        ActivityRow.kind == "model",
                        ActivityRow.status.in_(ACT_ACTIVE),
                    )
                )
            )
            if any(_loads(row.request_json).get("cancel_policy", "never") != "supersedable" for row in active_models):
                return ()
            processing_models = tuple(str(row.activity_id) for row in active_models if row.status == ACT_PROCESSING)
            session.execute(
                update(ActivityRow)
                .where(
                    ActivityRow.task_id == task_row.task_id,
                    ActivityRow.kind == "model",
                    ActivityRow.status.in_(ACT_ACTIVE),
                )
                .values(status=ACT_SUPERSEDED, error="superseded_by_new_context", updated_at=now)
            )
            lane.interrupt_count += 1
            lane.updated_at = now
            revision = int(lane.observed_revision)
            self._insert_causal_event(
                session,
                event_type="generation.superseded",
                summary=amp.payload.summary,
                payload={
                    "session_id": amp.payload.session_id,
                    "observed_revision": revision,
                    "interrupt_count": int(lane.interrupt_count),
                },
                task_id=str(task_row.task_id),
                correlation_id=amp.header.message_id,
                now=now,
            )
            self._end_task(
                session,
                str(task_row.task_id),
                TaskStatus.CANCELLED,
                f"superseded_by_revision:{revision}",
                now,
            )
            return processing_models

    def claim_message(self) -> tuple[AgentMessage, AgentInstance, Any] | None:
        """原子领取一条可处理消息（含其 Agent 与 Task），单进程无竞争。"""
        with self.session() as session:
            row = session.scalar(
                select(MessageRow)
                .where(MessageRow.status == MSG_PENDING)
                .order_by(MessageRow.priority.desc(), MessageRow.created_at, MessageRow.message_id)
                .limit(1)
            )
            if row is None:
                return None
            row.status = MSG_PROCESSING
            message = self._message(row)
            agent_row = session.scalar(select(AgentRow).where(AgentRow.agent_id == message.target_agent_id))
            task_row = session.scalar(select(TaskRow).where(TaskRow.task_id == message.task_id))
            if agent_row is None or task_row is None or task_row.status != TaskStatus.ACTIVE:
                row.status = MSG_ERROR
                row.completed_at = utc_now()
                return None
            return message, self._agent(agent_row), self._task(task_row)

    def fail_message(self, message_id: str, error: str) -> None:
        with self.session() as session:
            row = session.scalar(select(MessageRow).where(MessageRow.message_id == message_id))
            now = utc_now()
            if row is not None:
                row.status = MSG_ERROR
                row.completed_at = now
                self._insert_causal_event(
                    session,
                    event_type="message.failed",
                    summary=error,
                    payload={"message_id": message_id},
                    task_id=str(row.task_id),
                    agent_id=str(row.target_agent_id),
                    correlation_id=str(row.correlation_id),
                    now=now,
                )

    @staticmethod
    def _active_generation_filter() -> Any:
        """活动必须属于当前 generation：自主 Task 直接放行，交互 Task 校验 lane revision。"""
        return or_(
            TaskRow.autonomous == 1,
            (
                (SessionLaneRow.active_task_id == TaskRow.task_id)
                & (SessionLaneRow.generation_revision == ActivityRow.generation_revision)
            ),
        )

    def _generation_is_current(self, session: Session, task_row: TaskRow | None, generation_revision: int) -> bool:
        """判断活动是否仍可提交：Task 活跃且 generation 未被打断或取代。"""
        if task_row is None or task_row.status != TaskStatus.ACTIVE:
            return False
        if task_row.autonomous:
            return True
        lane = session.get(SessionLaneRow, str(task_row.session_id))
        return (
            lane is not None
            and lane.active_task_id == task_row.task_id
            and lane.generation_revision == generation_revision
        )

    def _notify_parent(
        self,
        session: Session,
        agent: AgentInstance,
        message: AgentMessage,
        *,
        status: Literal["completed", "failed"],
        summary: str,
        artifacts: tuple[Any, ...] = (),
        error: str | None = None,
        priority: int,
        now: str,
    ) -> str:
        """构造 ChildResult 并向父 Agent 投递 ``child.{status}`` 消息。"""
        target_agent_id = agent.parent_agent_id
        assert target_agent_id is not None
        payload = ChildResult(agent.agent_id, status, summary, artifacts, error).to_dict()
        return self._insert_message(
            session,
            task_id=agent.task_id,
            target_agent_id=target_agent_id,
            message_type=f"child.{status}",
            payload=payload,
            causation_id=message.message_id,
            correlation_id=agent.task_id,
            priority=priority,
            now=now,
        )

    def claim_activities(self, kind: str, limit: int) -> tuple[Any, ...]:
        """原子领取指定类型的待处理活动，返回活动实体。"""
        with self.session() as session:
            candidates = session.execute(
                select(ActivityRow, TaskRow.session_id)
                .join(TaskRow, TaskRow.task_id == ActivityRow.task_id)
                .outerjoin(SessionLaneRow, SessionLaneRow.session_id == TaskRow.session_id)
                .where(
                    ActivityRow.kind == kind,
                    ActivityRow.status == ACT_PENDING,
                    TaskRow.status == TASK_ACTIVE,
                    self._active_generation_filter(),
                )
                .order_by(ActivityRow.priority.desc(), ActivityRow.created_at)
            ).all()
            rows: list[Any] = []
            deferred: list[Any] = []
            sessions: set[str] = set()
            for row, session_id in candidates:
                if str(session_id) in sessions:
                    deferred.append(row)
                    continue
                rows.append(row)
                sessions.add(str(session_id))
                if len(rows) == limit:
                    break
            if len(rows) < limit:
                rows.extend(deferred[: limit - len(rows)])
            result: list[Any] = []
            for row in rows:
                row.status = ACT_PROCESSING
                row.updated_at = utc_now()
                result.append(row)
            return tuple(result)

    def complete_model_activity(self, activity_id: str, result: dict[str, Any] | None, error: str | None) -> None:
        """完成模型活动：写入结果并投递 model.completed / model.failed 消息。"""
        now = utc_now()
        with self.session() as session:
            row = session.scalar(
                select(ActivityRow).where(ActivityRow.activity_id == activity_id, ActivityRow.kind == "model")
            )
            if row is None:
                return
            if row.status == ACT_SUPERSEDED:
                self._record_late_model_result(session, row, error, now)
                return
            if row.status != ACT_PROCESSING:
                return
            task_row = session.scalar(select(TaskRow).where(TaskRow.task_id == row.task_id))
            if not self._generation_is_current(session, task_row, row.generation_revision):
                row.status = ACT_SUPERSEDED
                row.error = "late_result_for_superseded_generation"
                row.updated_at = now
                self._record_late_model_result(session, row, error, now)
                return
            row.status = ACT_COMPLETED if error is None else ACT_ERROR
            row.result_json = _json(result) if result is not None else None
            row.error = error
            row.updated_at = now
            if task_row is not None:
                payload: dict[str, Any] = (
                    {"activity_id": activity_id, "error": error}
                    if error is not None
                    else {"activity_id": activity_id, **(result or {})}
                )
                self._insert_message(
                    session,
                    task_id=str(row.task_id),
                    target_agent_id=str(row.agent_id),
                    message_type="model.completed" if error is None else "model.failed",
                    payload=payload,
                    causation_id=activity_id,
                    correlation_id=str(row.task_id),
                    priority=int(row.priority),
                    now=now,
                )

    @staticmethod
    def _record_late_model_result(session: Session, row: ActivityRow, error: str | None, now: str) -> None:
        StoreDecisionsMixin._insert_causal_event(
            session,
            event_type="generation.late_result_ignored",
            summary="late model result ignored",
            payload={"activity_id": str(row.activity_id), "reported_error": error is not None},
            task_id=str(row.task_id),
            agent_id=str(row.agent_id),
            causation_id=str(row.activity_id),
            correlation_id=str(row.task_id),
            now=now,
        )

    def claim_tool_activities(self, limit: int) -> tuple[Any, ...]:
        return self.claim_activities("tool", limit)

    def tool_recovery_activities(self) -> tuple[Any, ...]:
        with self.session() as session:
            rows = session.execute(
                select(ActivityRow)
                .join(TaskRow, TaskRow.task_id == ActivityRow.task_id)
                .outerjoin(SessionLaneRow, SessionLaneRow.session_id == TaskRow.session_id)
                .where(
                    ActivityRow.kind == "tool",
                    ActivityRow.status == ACT_PROCESSING,
                    TaskRow.status == TASK_ACTIVE,
                    self._active_generation_filter(),
                )
            ).scalars()
            return tuple(rows)

    def consume_tool_receipt(
        self,
        *,
        request_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """消费工具回执 AMP：幂等投递 tool.{status} 消息给请求方 Agent。

        幂等键为 request_id：因果事件中已存在同类型回执则忽略（重放去重）。
        """
        now = utc_now()
        with self.session() as session:
            existing = session.scalar(
                select(CausalEventRow.event_id).where(
                    CausalEventRow.correlation_id == request_id, CausalEventRow.event_type == event_type
                )
            )
            if existing is not None:
                return False, None
            row = session.scalar(
                select(ActivityRow).where(ActivityRow.idempotency_key == request_id, ActivityRow.kind == "tool")
            )
            if row is None or row.status != ACT_PROCESSING:
                return False, None
            task_row = session.get(TaskRow, str(row.task_id))
            if not self._generation_is_current(session, task_row, row.generation_revision):
                return False, None
            row.status = ACT_COMPLETED if event_type == "tool.succeeded" else ACT_ERROR
            row.result_json = _json(payload["result"]) if payload.get("result") is not None else None
            row.error = payload.get("error")
            row.updated_at = now
            request = _loads(row.request_json)
            if event_type == "tool.succeeded" and request.get("complete_task") is True:
                # 工具成功后自动完成 Agent（语义）：不投递 tool.succeeded 消息
                message_id = self._complete_agent_after_tool(session, row, summary, now)
            else:
                message_id = self._insert_message(
                    session,
                    task_id=str(row.task_id),
                    target_agent_id=str(row.agent_id),
                    message_type=event_type,
                    payload={**payload, "activity_id": row.activity_id, "request": request},
                    causation_id=request_id,
                    correlation_id=request_id,
                    priority=int(row.priority),
                    now=now,
                )
            self._insert_causal_event(
                session,
                event_type=event_type,
                summary=summary,
                payload={"request_id": request_id, "capability": payload.get("capability")},
                task_id=str(row.task_id),
                agent_id=str(row.agent_id),
                causation_id=request_id,
                correlation_id=request_id,
                now=now,
            )
            return True, message_id

    def _complete_agent_after_tool(self, session: Session, row: ActivityRow, summary: str, now: str) -> str | None:
        """工具成功后自动完成 Agent。

        若为根 Agent，结束整个 Task；否则向父 Agent 发送 child.completed 消息。
        """
        agent = session.scalar(select(AgentRow).where(AgentRow.agent_id == row.agent_id))
        if agent is None:
            return None
        agent.status = AgentStatus.COMPLETED
        agent.last_summary = summary
        agent.updated_at = now
        if agent.parent_agent_id is None:
            self._end_task(session, str(row.task_id), TaskStatus.COMPLETED, summary, now)
            return None
        result = ChildResult(
            child_agent_id=str(row.agent_id),
            status="completed",
            summary=summary,
            artifacts=(),
            error=None,
        )
        return self._insert_message(
            session,
            task_id=str(row.task_id),
            target_agent_id=str(agent.parent_agent_id),
            message_type="child.completed",
            payload=result.to_dict(),
            causation_id=str(row.activity_id),
            correlation_id=str(row.task_id),
            priority=int(row.priority),
            now=now,
        )

    def has_claimable_external_activity(self, limit: int) -> bool:
        with self.session() as session:
            processing = (
                session.scalar(
                    select(func.count())
                    .select_from(ActivityRow)
                    .where(ActivityRow.kind == "tool", ActivityRow.status == ACT_PROCESSING)
                )
                or 0
            )
            if processing >= limit:
                return False
            row = session.scalar(
                select(ActivityRow.activity_id)
                .join(TaskRow, TaskRow.task_id == ActivityRow.task_id)
                .where(ActivityRow.kind == "tool", ActivityRow.status == ACT_PENDING, TaskRow.status == TASK_ACTIVE)
                .limit(1)
            )
            return row is not None

    def has_recoverable_tool(self) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(ActivityRow.activity_id)
                .join(TaskRow, TaskRow.task_id == ActivityRow.task_id)
                .where(ActivityRow.kind == "tool", ActivityRow.status == ACT_PROCESSING, TaskRow.status == TASK_ACTIVE)
                .limit(1)
            )
            return row is not None

    # === Task 终止与预算 ===

    def cancel_task(self, task_id: str, reason: str) -> tuple[str, ...]:
        with self.session() as session:
            activities = tuple(
                str(value)
                for value in session.scalars(
                    select(ActivityRow.activity_id).where(
                        ActivityRow.task_id == task_id,
                        ActivityRow.kind == "model",
                        ActivityRow.status == ACT_PROCESSING,
                    )
                )
            )
            self._end_task(session, task_id, TaskStatus.CANCELLED, reason, utc_now())
            return activities

    def expire_tasks(self) -> tuple[str, ...]:
        """检查并终止所有超时的活跃 Task（duration 预算）。"""
        now_dt = datetime.now(UTC)
        expired: list[str] = []
        with self.session() as session:
            rows = session.execute(select(TaskRow).where(TaskRow.status == TASK_ACTIVE)).scalars()
            for row in rows:
                if (now_dt - datetime.fromisoformat(row.started_at)).total_seconds() <= row.max_duration_seconds:
                    continue
                self._end_task(
                    session,
                    str(row.task_id),
                    TaskStatus.BUDGET_EXHAUSTED,
                    "duration_budget_exhausted",
                    now_dt.isoformat(),
                )
                expired.append(str(row.task_id))
        return tuple(expired)

    # === 内部辅助 ===

    @staticmethod
    def _root_batch_events(state: dict[str, Any]) -> list[Any] | None:
        """入口 agent 状态中的批次投影；仅 triage 创建的根 agent 携带。"""
        events = state.get("batch_events")
        return events if isinstance(events, list) else None

    @staticmethod
    def _require_triage_root(agent: AgentInstance, task_row: TaskRow) -> None:
        """defer/discard 只允许入口 triage agent 发出。"""
        if agent.agent_id != task_row.root_agent_id:
            raise PermissionError(_Msg.TRIAGE_CONTROL_DENIED)

    @staticmethod
    def _has_active_children(session: Session, agent_id: str) -> bool:
        """派生等待前提：非终态 children 或 pending child reports。"""
        if (
            session.scalar(
                select(AgentRow.agent_id)
                .where(AgentRow.parent_agent_id == agent_id, AgentRow.status.not_in(AGENT_TERMINAL))
                .limit(1)
            )
            is not None
        ):
            return True
        return (
            session.scalar(
                select(MessageRow.message_id)
                .where(
                    MessageRow.target_agent_id == agent_id,
                    MessageRow.message_type.in_(("child.completed", "child.failed")),
                    MessageRow.status == MSG_PENDING,
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _end_task(session: Session, task_id: str, status: TaskStatus, reason: str, now: str) -> None:
        """终止 Task：更新 Task 状态为终止态，级联取消所有非终态 Agent、消息和 Activity。"""
        task_row = session.get(TaskRow, task_id)
        if task_row is not None:
            if reason.startswith("superseded_by_revision:"):
                session.execute(
                    update(InboxEventRow)
                    .where(InboxEventRow.batch_id == task_row.root_message_id)
                    .values(status=INBOX_PENDING, batch_id=None, available_at=now, updated_at=now)
                )
            else:
                session.execute(delete(InboxEventRow).where(InboxEventRow.batch_id == task_row.root_message_id))
        if (
            task_row is not None
            and task_row.status == TaskStatus.ACTIVE
            and status in {TaskStatus.COMPLETED, TaskStatus.ERROR}
        ):
            StoreDecisionsMixin._publish_task_outputs(session, task_row, now)
        if task_row is not None and not task_row.autonomous:
            lane = session.get(SessionLaneRow, str(task_row.session_id))
            if lane is not None and lane.active_task_id == task_id:
                lane.active_task_id = None
                lane.updated_at = now
                if not reason.startswith("superseded_by_revision:"):
                    if status in {TaskStatus.COMPLETED, TaskStatus.SILENT, TaskStatus.ERROR}:
                        lane.committed_revision = max(
                            int(lane.committed_revision),
                            int(lane.generation_revision),
                        )
                    lane.interrupt_count = 0
                    lane.generation_started_at = None
        session.execute(
            update(TaskRow)
            .where(TaskRow.task_id == task_id)
            .values(status=status, termination_reason=reason, updated_at=now)
        )
        session.execute(
            update(AgentRow)
            .where(AgentRow.task_id == task_id, AgentRow.status.not_in(AGENT_TERMINAL))
            .values(status=AGENT_CANCELLED, updated_at=now)
        )
        session.execute(
            update(MessageRow)
            .where(MessageRow.task_id == task_id, MessageRow.status.in_((MSG_PENDING, MSG_PROCESSING)))
            .values(status=MSG_ERROR, completed_at=now)
        )
        session.execute(
            update(ActivityRow)
            .where(ActivityRow.task_id == task_id, ActivityRow.status.in_(ACT_ACTIVE))
            .values(status=ACT_CANCELLED, updated_at=now)
        )

    @staticmethod
    def _publish_task_outputs(session: Session, task_row: TaskRow, now: str) -> None:
        rows = session.execute(
            select(ActivityRow)
            .where(
                ActivityRow.task_id == task_row.task_id,
                ActivityRow.publishable == 1,
                ActivityRow.status.in_((ACT_COMPLETED, ACT_ERROR)),
            )
            .order_by(ActivityRow.created_at, ActivityRow.activity_id)
        ).scalars()
        for row in rows:
            result = _loads(row.result_json)
            kind = "error" if row.status == ACT_ERROR else "model"
            text = str(row.error or "")
            if kind == "model" and isinstance(result, dict):
                text = str(result.get("text", ""))
            session.add(
                OutputPublicationRow(
                    activity_id=str(row.activity_id),
                    task_id=str(task_row.task_id),
                    session_id=str(task_row.session_id),
                    generation_revision=int(row.generation_revision),
                    kind=kind,
                    text=text,
                    created_at=now,
                )
            )


def _requests_interrupt(amp: Any) -> bool:
    if amp.payload.type != "message.received":
        return False
    data = amp.payload.data
    attention = data.get("attention")
    if attention in {"direct", "correction", "urgent"}:
        return True
    if any(data.get(name) is True for name in ("directed", "mentioned", "reply_to_bot")):
        return True
    return ":private:" in amp.payload.session_id
