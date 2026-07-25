"""engine 的持久化状态、Agent 调度与因果边界。

EngineState 拥有 Task/Agent 持久化状态、邮箱队列和 Activity 调度，
并将所有认知决策委托给外部 Agent handler，将 I/O 委托给平台层。
这是 Aurora 运行时闭环的唯一入口。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.contracts.agent import (
    ActivityRequest,
    AgentHandler,
    AgentInstance,
    AgentLimits,
    BrainContextSnapshot,
    CapabilityCatalogSnapshot,
    EngineConfiguration,
    TaskState,
    TaskStatus,
    ToolLease,
)
from src.engine.brain import build_brain_context
from src.engine.debug import agent_detail as build_agent_detail
from src.engine.debug import reject_active_legacy_workspace
from src.engine.debug import task_detail as build_task_detail
from src.engine.runtime_decisions import apply_authorized_decision, apply_failure, handle_claim
from src.engine.runtime_ingress import ingest_ready as ingest_runtime_ready
from src.engine.store import SQLiteRuntimeStore
from src.utils.logging import get_logger
from src.utils.serialization import atomic_write_json

if TYPE_CHECKING:
    from src.contracts.amp import AmpEnvelope
    from src.contracts.memory import MemoryStore
    from src.contracts.tool import ToolOutcomeStatus

from src.contracts.memory import MemoryContextSnapshot, MemoryEntry

logger = get_logger("aurora.engine")


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    HANDLERS_MISMATCH = "Agent handlers must exactly match configured profiles"
    ROOT_PROFILE_MISSING = "root Agent profile is not configured"
    CATALOG_ALREADY_INSTALLED = "capability catalog is already installed"
    MAX_TURNS_POSITIVE = "max_turns must be positive"
    INVALID_TOOL_OUTCOME = "invalid Tool outcome"
    TOOL_COMPLETION_UNMATCHED = "Tool completion does not match an active request: {request_id}"


@dataclass(frozen=True, slots=True)
class PumpResult:
    """单次 pump 调用的结果统计。

    包含本次摄入的 Task/Situation ID、成功处理的消息 ID 和失败的消息 ID。
    """

    ingested_task_ids: tuple[str, ...]
    processed_message_ids: tuple[str, ...]
    failed_message_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EngineState:
    """拥有持久化 Task/Agent 状态，将所有认知和外部 I/O 委托出去。

    核心职责：
    - pump：周期性摄入 AMP 事件、领取邮箱消息、执行 Agent turn、应用决策
    - 因果边界：所有状态变更通过 causal_events 表记录
    - 预算控制：模型和工具调用均有硬上限
    - 监督树：子 Agent 创建受深度、数量和全局上限约束
    """

    def __init__(
        self,
        configuration: EngineConfiguration,
        handlers: dict[str, AgentHandler],
        memory_store: MemoryStore | None = None,
    ) -> None:
        """初始化 Agent 内核。

        验证 handler 与 profile 一一对应，创建工作区目录结构，
        初始化三个线程池执行器（SQLite 写入、Agent turn、阻塞操作），
        并执行数据库迁移和中断恢复。
        """
        self.configuration = configuration
        self._profiles = {profile.id: profile for profile in configuration.profiles}
        if set(self._profiles) != set(handlers):
            raise ValueError(_Msg.HANDLERS_MISMATCH)
        if configuration.limits.root_profile not in self._profiles:
            raise ValueError(_Msg.ROOT_PROFILE_MISSING)
        self._handlers = handlers
        self._memory_store = memory_store
        self._workspace = Path(configuration.workspace)
        self._inbox = self._workspace / "inbox"
        self._process = self._workspace / "process"
        self._archive = self._workspace / "archive"
        self._task_archive = self._archive / "tasks"
        for directory in (self._inbox, self._process, self._archive, self._task_archive):
            directory.mkdir(parents=True, exist_ok=True)
        self._amp_queue: list[AmpEnvelope] = []
        reject_active_legacy_workspace(self._process)
        self._store_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aurora-sqlite-writer")
        self._turn_executor = ThreadPoolExecutor(
            max_workers=configuration.limits.turn_concurrency,
            thread_name_prefix="aurora-agent-turn",
        )
        self._blocking_executor = ThreadPoolExecutor(
            max_workers=configuration.limits.blocking_workers,
            thread_name_prefix="aurora-blocking",
        )
        self.store = SQLiteRuntimeStore(self._process / "runtime.sqlite3")
        self._store_executor.submit(self.store.initialize).result()
        self._capability_catalog: CapabilityCatalogSnapshot | None = None
        self._lock = asyncio.Lock()
        logger.info(
            "Agent engine state initialized workspace=%s profiles=%d active_tasks=%d",
            self._workspace,
            len(self._profiles),
            self.store.counts()["active_tasks"],
        )

    @property
    def limits(self) -> AgentLimits:
        return self.configuration.limits

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        return self._capability_catalog or CapabilityCatalogSnapshot()

    def install_capability_catalog(self, catalog: CapabilityCatalogSnapshot) -> None:
        """安装外部能力目录。仅能调用一次，重复调用将抛出 RuntimeError。"""
        if self._capability_catalog is not None:
            raise RuntimeError(_Msg.CATALOG_ALREADY_INSTALLED)
        self._capability_catalog = catalog

    async def submit_amp(self, amp: AmpEnvelope) -> None:
        """将 AMP Envelope 加入内存队列，供下次 pump 周期摄入。"""
        async with self._lock:
            self._amp_queue.append(amp)

    def ingest_ready(self) -> tuple[str, ...]:
        """同步摄入所有就绪的 AMP 输入（内存队列 + inbox 文件）。"""
        return ingest_runtime_ready(self)

    def brain_context(self) -> BrainContextSnapshot:
        """构建全局 Brain 上下文快照，聚合所有活跃 Task 和 Agent 的摘要信息。"""
        return build_brain_context(self.store)

    def recall_memory(self, query: str) -> MemoryContextSnapshot:
        """通过注入的 Port 召回 turn 上下文；服务失败时返回空快照。"""
        if self._memory_store is None:
            return MemoryContextSnapshot()
        try:
            return self._memory_store.recall(query)
        except Exception as error:
            logger.warning("Memory recall failed error_type=%s", type(error).__name__)
            return MemoryContextSnapshot()

    def completed_memory_entries(self) -> tuple[MemoryEntry, ...]:
        """投影可交给自动记忆服务的已完成交互。"""
        entries = []
        for task in self.store.tasks():
            if task.autonomous or task.status not in {TaskStatus.COMPLETED, TaskStatus.SILENT}:
                continue
            agent = self.store.get_agent(task.root_agent_id)
            if agent is None:
                continue
            entries.append(MemoryEntry(task.task_id, task.root_summary, agent.last_summary or None, task.updated_at))
        return tuple(entries)

    async def pump(self, max_turns: int | None = None) -> PumpResult:
        """摄入就绪的 AMP 文件并处理一批独立的 Agent turn。

        流程：摄入 → 过期检查 → 领取消息 → 并发执行 Agent turn → 应用决策 → 归档终止 Task。
        max_turns 限制单次 pump 处理的最大 turn 数，未指定时使用配置中的 turn_concurrency。
        """
        limit = self.limits.turn_concurrency if max_turns is None else max_turns
        if limit <= 0:
            raise ValueError(_Msg.MAX_TURNS_POSITIVE)
        ingested, claims = await self._ingest_and_claim(limit)
        if not claims:
            await self._blocking_call(self._archive_terminal_tasks)
            return PumpResult(ingested, (), ())
        decisions = await self._execute_claims(claims)
        result = await self._apply_results(ingested, claims, decisions)
        await self._blocking_call(self._archive_terminal_tasks)
        return result

    async def _ingest_and_claim(self, limit: int) -> tuple[tuple[str, ...], tuple[Any, ...]]:
        """加锁摄入 AMP + 过期检查 + 领取邮箱消息，返回 (摄入ID列表, 领取的消息列表)。"""
        async with self._lock:
            ingested = await self._store_call(self.ingest_ready)
            await self._store_call(self.store.expire_tasks)
            await self._store_call(self.store.expire_situations)
            claims = await self._store_call(self._claim_messages, limit)
            return ingested, claims

    async def _execute_claims(self, claims: tuple[Any, ...]) -> tuple[Any, ...]:
        """在线程池中并发执行所有已领取的 Agent turn。返回每个 turn 的决策或异常。"""
        loop = asyncio.get_running_loop()
        return tuple(
            await asyncio.gather(
                *(loop.run_in_executor(self._turn_executor, handle_claim, self, claim) for claim in claims),
                return_exceptions=True,
            )
        )

    async def _apply_results(
        self, ingested: tuple[str, ...], claims: tuple[Any, ...], decisions: tuple[Any, ...]
    ) -> PumpResult:
        """将 Agent turn 的执行结果（决策或异常）应用到仓库中。"""
        processed: list[str] = []
        failed: list[str] = []
        for claim, result in zip(claims, decisions, strict=True):
            message, agent, _task = claim
            try:
                if isinstance(result, BaseException):
                    raise result
                await self._store_call(apply_authorized_decision, self, message, agent, result)
                processed.append(message.message_id)
            except Exception as error:
                logger.log(
                    logging.ERROR,
                    "Agent turn failed task_id=%s agent_id=%s message_id=%s error_type=%s",
                    agent.task_id,
                    agent.agent_id,
                    message.message_id,
                    type(error).__name__,
                )
                try:
                    await self._store_call(apply_failure, self, message, agent, f"{type(error).__name__}: {error}")
                except Exception:
                    await self._store_call(self.store.fail_message, message.message_id, agent.agent_id, str(error))
                failed.append(message.message_id)
        return PumpResult(ingested, tuple(processed), tuple(failed))

    async def _store_call(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        """在 SQLite 写入线程池中同步执行数据库操作。确保所有写操作串行化。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._store_executor, partial(function, *args, **kwargs))

    async def _blocking_call(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        """在阻塞线程池中执行可能耗时较长的 I/O 操作（如文件归档）。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._blocking_executor, partial(function, *args, **kwargs))

    def _claim_messages(self, limit: int) -> tuple[Any, ...]:
        """领取至多 limit 条邮箱消息，每条通过 CAS 获取租约。"""
        claims = []
        for _ in range(limit):
            claimed = self.store.claim_message(self.limits.lease_seconds)
            if claimed is None:
                break
            claims.append(claimed)
        return tuple(claims)

    def has_work(self) -> bool:
        """检查是否有待处理的工作。这是主调度循环的触发条件。

        包括：AMP 队列、inbox 文件、待处理消息、可领取的外部 Activity、可恢复的工具。
        """
        counts = self.store.counts()
        return (
            bool(self._amp_queue)
            or any(self._inbox.glob("*.json"))
            or counts["pending_messages"] > 0
            or self.store.has_claimable_external_activity(self.limits.tool_concurrency)
            or self.store.has_recoverable_tool()
        )

    def has_pending_tool_requests(self) -> bool:
        """检查是否有待处理的工具 Activity。"""
        return self.store.counts()["pending_tool_activities"] > 0

    def has_pending_model_requests(self) -> bool:
        """检查是否有待处理的 PENDING 模型 Activity。"""
        with self.store.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM activities WHERE kind = 'model' AND status = 'PENDING' LIMIT 1"
                ).fetchone()
            )

    async def claim_model_requests(self, limit: int) -> tuple[ActivityRequest, ...]:
        """领取至多 limit 个 PENDING 模型 Activity，设置租约。"""
        return await self._store_call(self.store.claim_activities, "model", limit, self.limits.lease_seconds)

    async def complete_model(self, activity: ActivityRequest, result: dict[str, Any] | None, error: str | None) -> None:
        """完成模型 Activity 并投递对应消息到 Agent 邮箱。"""
        await self._store_call(self.store.complete_model_activity, activity.activity_id, result, error)

    async def claim_tool_requests(self) -> tuple[ToolLease, ...]:
        """领取 PENDING 工具 Activity 并构造 ToolLease 列表。受 tool_concurrency 限制。"""
        activities = await self._store_call(
            self.store.claim_tool_activities,
            self.limits.tool_concurrency,
            self.limits.lease_seconds,
        )
        leases = []
        for activity in activities:
            request = activity.request
            leases.append(
                ToolLease(
                    activity_id=activity.activity_id,
                    task_id=activity.task_id,
                    agent_id=activity.agent_id,
                    request_id=activity.idempotency_key,
                    session_id=str(request["session_id"]),
                    capability=str(request["capability"]),
                    parameters=dict(request["parameters"]),
                )
            )
        return tuple(leases)

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]:
        """获取所有租约过期的工具 Activity 以恢复执行。用于重启后重新分发。"""
        activities = await self._store_call(self.store.tool_recovery_activities)
        return tuple(
            ToolLease(
                activity.activity_id,
                activity.task_id,
                activity.agent_id,
                activity.idempotency_key,
                str(activity.request["session_id"]),
                str(activity.request["capability"]),
                dict(activity.request["parameters"]),
            )
            for activity in activities
        )

    async def complete_tool(
        self,
        *,
        request_id: str,
        capability: str,
        status: ToolOutcomeStatus,
        summary: str,
        result: dict[str, Any] | None,
        error: str | None,
        source_app: str,
        source_instance: str,
    ) -> None:
        """完成工具调用，校验状态一致性并通过幂等键写入。

        校验状态（succeeded/failed/unknown）与 result/error 的对应关系，
        通过 uuid5 生成确定性收据 ID 实现幂等，匹配原始 Activity 后写入。
        """
        if status not in {"succeeded", "failed", "unknown"}:
            raise ValueError(_Msg.INVALID_TOOL_OUTCOME)
        if (status == "succeeded" and error is not None) or (
            status != "succeeded" and (not error or result is not None)
        ):
            raise ValueError(_Msg.INVALID_TOOL_OUTCOME)
        event_type = f"tool.{status}"
        # 通过 uuid5 生成确定性收据 ID，确保同一请求 + 事件类型的组合幂等
        receipt_id = str(uuid5(NAMESPACE_URL, f"aurora-tool-receipt:{request_id}:{event_type}"))
        matched, _message_id = await self._store_call(
            self.store.complete_tool_activity,
            external_message_id=receipt_id,
            request_id=request_id,
            event_type=event_type,
            summary=summary,
            payload={
                "request_id": request_id,
                "capability": capability,
                "result": result,
                "error": error,
                "source": {"app": source_app, "instance": source_instance},
            },
        )
        if not matched:
            raise ValueError(_Msg.TOOL_COMPLETION_UNMATCHED.format(request_id=request_id))

    def tasks(self) -> tuple[TaskState, ...]:
        """返回仓库中所有 Task。"""
        return self.store.tasks()

    def get_task(self, task_id: str) -> TaskState | None:
        """按 task_id 查找 Task，不存在返回 None。"""
        return self.store.get_task(task_id)

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        """按 agent_id 查找 Agent，不存在返回 None。"""
        return self.store.get_agent(agent_id)

    def task_detail(self, task_id: str) -> dict[str, Any] | None:
        """获取 Task 详情投影（含监督树和因果事件）。"""
        return build_task_detail(self.store, task_id)

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        """获取 Agent 详情投影（含子节点和消息时间线）。"""
        return build_agent_detail(self.store, agent_id)

    def status(self) -> dict[str, Any]:
        """返回内核运行时状态快照：聚合计数 + Brain 上下文生成时间。"""
        return {**self.store.counts(), "brain_context_generated_at": self.brain_context().generated_at}

    async def cancel_task(self, task_id: str, reason: str) -> None:
        """取消指定 Task，将其状态设为 CANCELLED 并级联终止。"""
        await self._store_call(self.store.cancel_task, task_id, reason)
        await self._blocking_call(self._archive_terminal_tasks)

    async def cancel_autonomous_tasks(self, reason: str) -> tuple[str, ...]:
        """取消所有自主 Task（autonomous=True）。返回被取消的 task_id 列表。"""
        cancelled = []
        for task in self.store.tasks(active_only=True):
            if task.autonomous:
                await self._store_call(self.store.cancel_task, task.task_id, reason)
                cancelled.append(task.task_id)
        await self._blocking_call(self._archive_terminal_tasks)
        return tuple(cancelled)

    def _archive_terminal_tasks(self) -> None:
        """将已终止的 Task 详情以 JSON 原子写入归档目录。通过原子写 + 先检查存在性防止重复。"""
        for task in self.store.tasks():
            if not task.terminal:
                continue
            destination = self._task_archive / f"{task.task_id}.json"
            if destination.exists():
                continue
            detail = self.task_detail(task.task_id)
            if detail is not None:
                atomic_write_json(destination, detail)

    def reset_workspace_for_tests(self) -> None:
        """仅测试使用：关闭内核并删除整个工作区目录。"""
        self.shutdown()
        shutil.rmtree(self._workspace)

    def shutdown(self) -> None:
        """优雅关闭内核：清空 AMP 队列，关闭所有线程池执行器。"""
        self._amp_queue.clear()
        self._turn_executor.shutdown(wait=True, cancel_futures=True)
        self._blocking_executor.shutdown(wait=True, cancel_futures=True)
        self._store_executor.shutdown(wait=True, cancel_futures=True)
