"""完整拥有 Agent pump 热路径的运行时引擎。

AgentEngine 是外部可见的唯一入口——组合持久化状态、模型、工具与自动记忆服务。
EngineState 拥有 Task/Agent 持久化状态、邮箱队列和 Activity 调度，
将所有认知决策委托给外部 Agent handler，将 I/O 委托给平台层。
决策构造/授权与 AMP 摄入分别位于 engine/authorize.py 与 engine/ingress.py（RFC 0208）。
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

from src.contracts import (
    ActivityRequest,
    AgentHandler,
    AgentInstance,
    AgentLimits,
    AmpEnvelope,
    CapabilityCatalogSnapshot,
    EngineConfiguration,
    MemoryContextSnapshot,
    MemoryEntry,
    MemoryQuery,
    ModelRequest,
    OutputStreamItem,
    OutputStreamPage,
    TaskState,
    TaskStatus,
    ToolLease,
    ToolRequest,
    TriageBatch,
)
from src.engine.archive import (
    TASK_ARCHIVE_VERSION,
    archived_agent_detail,
    read_task_archive,
    task_archive_projection,
)
from src.engine.authorize import (
    apply_authorized_decision,
    apply_failure,
    handle_claim,
)
from src.engine.debug import agent_detail as build_agent_detail
from src.engine.debug import reject_active_legacy_workspace
from src.engine.debug import task_detail as build_task_detail
from src.engine.ingress import ingest_ready, persist_amp
from src.engine.session_log import SessionLog
from src.engine.store import SQLiteRuntimeStore
from src.engine.store.status import ACT_PENDING
from src.engine.tool_registry import ToolRegistry
from src.utils import (
    atomic_write_json,
    get_logger,
)

if TYPE_CHECKING:
    from src.contracts.memory import MemoryStore
    from src.contracts.model import ModelProvider
    from src.contracts.tool import ToolExecutorBinding

logger = get_logger("aurora.engine")


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    RESERVED_EVENT_TYPE = "reserved internal event type: {amp_type}"
    HANDLERS_MISMATCH = "Agent handlers must exactly match configured profiles"
    ROOT_PROFILE_MISSING = "root Agent profile is not configured"
    CATALOG_ALREADY_INSTALLED = "capability catalog is already installed"
    MAX_TURNS_POSITIVE = "max_turns must be positive"
    INVALID_TOOL_OUTCOME = "invalid Tool outcome"
    TOOL_COMPLETION_UNMATCHED = "Tool completion does not match an active request: {request_id}"


# -- 类型与工具函数 ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PumpResult:
    ingested_event_ids: tuple[str, ...]
    admitted_task_ids: tuple[str, ...]
    processed_message_ids: tuple[str, ...]
    failed_message_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -- 引擎核心 ------------------------------------------------------------


class EngineState:
    """拥有持久化 Task/Agent 状态，将所有认知和外部 I/O 委托出去。"""

    def __init__(
        self,
        configuration: EngineConfiguration,
        handlers: dict[str, AgentHandler],
        memory_store: MemoryStore | None = None,
    ) -> None:
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
        self._session_log = SessionLog(self._workspace / "sessions")
        for directory in (self._inbox, self._process, self._archive, self._task_archive):
            directory.mkdir(parents=True, exist_ok=True)
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
        self._archive_terminal_tasks()
        self._prune_archived_terminal_tasks()
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
        if self._capability_catalog is not None:
            raise RuntimeError(_Msg.CATALOG_ALREADY_INSTALLED)
        self._capability_catalog = catalog

    async def submit_amp(self, amp: AmpEnvelope) -> None:
        async with self._lock:
            await self._store_call(persist_amp, self, amp)

    def _ingest_ready(self) -> tuple[str, ...]:
        return ingest_ready(self)

    def recall_memory(self, query: MemoryQuery) -> MemoryContextSnapshot:
        if self._memory_store is None:
            return MemoryContextSnapshot()
        try:
            return self._memory_store.recall(query)
        except Exception as error:
            logger.warning("Memory recall failed error_type=%s", type(error).__name__)
            return MemoryContextSnapshot()

    def completed_memory_entries(self) -> tuple[MemoryEntry, ...]:
        entries = []
        for task in self.store.tasks():
            if task.autonomous or task.status not in {TaskStatus.COMPLETED, TaskStatus.SILENT}:
                continue
            agent = self.store.get_agent(task.root_agent_id)
            if agent is None:
                continue
            entries.append(
                MemoryEntry(
                    task_id=task.task_id,
                    scope=task.session_id,
                    input_summary=task.root_summary,
                    outcome_summary=agent.last_summary or None,
                    created_at=task.updated_at,
                    fact_candidates=self._memory_candidates(task.task_id),
                )
            )
        return tuple(entries)

    def _memory_candidates(self, task_id: str) -> tuple[str, ...]:
        candidates: list[str] = []
        for event in self.store.events_for_task(task_id):
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            raw = payload.get("memory_candidates")
            if isinstance(raw, list):
                candidates.extend(str(item) for item in raw if isinstance(item, str) and item.strip())
        return tuple(dict.fromkeys(candidates))

    async def ingest(self) -> tuple[str, ...]:
        """只把 AMP 写入持久化 Inbox，不创建 Task。"""
        async with self._lock:
            return await self._store_call(self._ingest_ready)

    async def claim_triage_batches(self, limit: int) -> tuple[TriageBatch, ...]:
        return await self._store_call(self.store.claim_triage_batches, self.configuration.triage, limit)

    async def create_triage_task(self, batch: TriageBatch) -> str | None:
        """防抖批次到期后创建 Task 与入口 triage agent（RFC 0209）。"""
        priority = max((event.priority for event in batch.events), default=100)
        created = await self._store_call(
            self.store.create_triage_task,
            batch,
            triage_profile=self.limits.root_profile,
            interactive_budget=self.configuration.interactive_budget,
            autonomous_budget=self.configuration.autonomous_budget,
            priority=priority,
        )
        if created is not None:
            task_id, summary = created
            self._session_log.task_admitted(task_id, batch.session_id, summary)
        return created[0] if created is not None else None

    async def pump(self, max_turns: int | None = None) -> PumpResult:
        limit = self.limits.turn_concurrency if max_turns is None else max_turns
        if limit <= 0:
            raise ValueError(_Msg.MAX_TURNS_POSITIVE)
        claims = await self._expire_and_claim(limit)
        if not claims:
            await self._blocking_call(self._archive_terminal_tasks)
            return PumpResult((), (), (), ())
        decisions = await self._execute_claims(claims)
        result = await self._apply_results(claims, decisions)
        await self._blocking_call(self._archive_terminal_tasks)
        return result

    async def _expire_and_claim(self, limit: int) -> tuple[Any, ...]:
        async with self._lock:
            await self._store_call(self.store.expire_tasks)
            return await self._store_call(self._claim_messages, limit)

    async def _execute_claims(self, claims: tuple[Any, ...]) -> tuple[Any, ...]:
        loop = asyncio.get_running_loop()
        return tuple(
            await asyncio.gather(
                *(loop.run_in_executor(self._turn_executor, handle_claim, self, claim) for claim in claims),
                return_exceptions=True,
            )
        )

    async def _apply_results(self, claims: tuple[Any, ...], decisions: tuple[Any, ...]) -> PumpResult:
        processed: list[str] = []
        failed: list[str] = []
        for claim, result in zip(claims, decisions, strict=True):
            message, agent, _task = claim
            try:
                if isinstance(result, BaseException):
                    raise result  # noqa: TRY301
                decision, profile_id = result
                await self._store_call(apply_authorized_decision, self, message, agent, profile_id, decision)
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
        return PumpResult((), (), tuple(processed), tuple(failed))

    async def _store_call(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._store_executor, partial(function, *args, **kwargs))

    async def _blocking_call(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._blocking_executor, partial(function, *args, **kwargs))

    def _claim_messages(self, limit: int) -> tuple[Any, ...]:
        claims = []
        for _ in range(limit):
            claimed = self.store.claim_message(self.limits.lease_seconds)
            if claimed is None:
                break
            claims.append(claimed)
        return tuple(claims)

    def has_work(self) -> bool:
        counts = self.store.counts()
        return (
            any(self._inbox.glob("*.json"))
            or self.store.has_due_inbox()
            or counts["pending_messages"] > 0
            or self.store.has_claimable_external_activity(self.limits.tool_concurrency)
            or self.store.has_recoverable_tool()
        )

    def has_pending_tool_requests(self) -> bool:
        return self.store.counts()["pending_tool_activities"] > 0

    def has_pending_model_requests(self) -> bool:
        with self.store.connect() as connection:
            return bool(
                connection.execute(
                    f"SELECT 1 FROM activities WHERE kind = 'model' AND status = {ACT_PENDING} LIMIT 1"
                ).fetchone()
            )

    async def claim_model_requests(self, limit: int) -> tuple[ActivityRequest, ...]:
        return await self._store_call(self.store.claim_activities, "model", limit, self.limits.lease_seconds)

    async def complete_model(self, activity: ActivityRequest, result: dict[str, Any] | None, error: str | None) -> None:
        await self._store_call(self.store.complete_model_activity, activity.activity_id, result, error)

    async def claim_tool_requests(self) -> tuple[ToolLease, ...]:
        activities = await self._store_call(
            self.store.claim_tool_activities,
            self.limits.tool_concurrency,
            self.limits.lease_seconds,
        )
        return tuple(self._tool_lease(activity) for activity in activities)

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]:
        activities = await self._store_call(self.store.tool_recovery_activities)
        return tuple(self._tool_lease(activity) for activity in activities)

    @staticmethod
    def _tool_lease(activity: ActivityRequest) -> ToolLease:
        """将持久化的工具活动请求解析为类型化租约。"""
        request = ToolRequest.from_dict(activity.request)
        return ToolLease(
            activity_id=activity.activity_id,
            task_id=activity.task_id,
            agent_id=activity.agent_id,
            request_id=activity.idempotency_key,
            session_id=str(activity.request["session_id"]),
            capability=request.capability,
            parameters=request.parameters,
        )

    async def complete_tool(
        self,
        *,
        request_id: str,
        capability: str,
        status: Any,
        summary: str,
        result: dict[str, Any] | None,
        error: str | None,
        source_app: str,
        source_instance: str,
    ) -> None:
        if status not in {"succeeded", "failed", "unknown"}:
            raise ValueError(_Msg.INVALID_TOOL_OUTCOME)
        if (status == "succeeded" and error is not None) or (
            status != "succeeded" and (not error or result is not None)
        ):
            raise ValueError(_Msg.INVALID_TOOL_OUTCOME)
        event_type = f"tool.{status}"
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
        return self.store.tasks()

    def get_task(self, task_id: str) -> TaskState | None:
        return self.store.get_task(task_id)

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        return self.store.get_agent(agent_id)

    def task_detail(self, task_id: str) -> dict[str, Any] | None:
        detail = build_task_detail(self.store, task_id)
        if detail is not None:
            return detail
        archive = self._task_archive / f"{task_id}.json"
        return read_task_archive(archive, task_id)

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        detail = build_agent_detail(self.store, agent_id)
        if detail is not None:
            return detail
        return archived_agent_detail(self._task_archive, agent_id)

    def status(self) -> dict[str, Any]:
        return self.store.counts()

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage:
        """返回游标之后新增的用户可见模型输出（只读）。"""
        rows = self.store.recent_outputs(cursor, limit=limit)
        items = tuple(OutputStreamItem(**row) for row in rows)
        next_cursor = items[-1].cursor if items else cursor
        return OutputStreamPage(items=items, next_cursor=next_cursor)

    async def cancel_task(self, task_id: str, reason: str) -> None:
        await self._store_call(self.store.cancel_task, task_id, reason)
        await self.finalize_terminal_tasks()

    def _archive_terminal_tasks(self) -> None:
        for task in self.store.tasks():
            if not task.terminal:
                continue
            destination = self._task_archive / f"{task.task_id}.json"
            archived = read_task_archive(destination, task.task_id)
            if archived is not None and archived.get("archive_version") == TASK_ARCHIVE_VERSION:
                continue
            detail = archived or build_task_detail(self.store, task.task_id)
            if detail is not None:
                atomic_write_json(destination, task_archive_projection(detail), compact=True)
                self._session_log.task_finished(task)

    def _prune_archived_terminal_tasks(self) -> None:
        pruned = False
        for task in self.store.tasks():
            archive = self._task_archive / f"{task.task_id}.json"
            if task.terminal and read_task_archive(archive, task.task_id) is not None:
                pruned = self.store.prune_archived_task(task.task_id) or pruned
        if pruned:
            self.store.maintain_storage()

    async def finalize_terminal_tasks(self) -> None:
        """确保终态 Task 已归档后，将其从热库清除。"""
        await self._blocking_call(self._archive_terminal_tasks)
        await self._store_call(self._prune_archived_terminal_tasks)

    def reset_workspace_for_tests(self) -> None:
        self.shutdown()
        shutil.rmtree(self._workspace)

    def shutdown(self) -> None:
        self._turn_executor.shutdown(wait=True, cancel_futures=True)
        self._blocking_executor.shutdown(wait=True, cancel_futures=True)
        self._store_executor.shutdown(wait=True, cancel_futures=True)


# -- 引擎门面 ------------------------------------------------------------


class AgentEngine:
    """组合持久化状态、模型、工具与自动记忆服务的完整 Agent 引擎。

    EngineState 拥有内部热路径；AgentEngine 是外部唯一可见的入口，
    负责 I/O 编排——模型派发、工具执行、记忆 hooks、主事件循环。
    """

    def __init__(
        self,
        configuration: EngineConfiguration,
        handlers: dict[str, AgentHandler],
        *,
        model_provider: ModelProvider,
        tool_registry: ToolRegistry | None = None,
        memory_store: MemoryStore | None = None,
        idle_wait_seconds: float = 1.0,
    ) -> None:
        self.configuration = configuration
        self._state = EngineState(configuration, handlers, memory_store)
        self._model_provider = model_provider
        self._memory_store = memory_store
        self._idle_wait_seconds = idle_wait_seconds
        self._tools = tool_registry if tool_registry is not None else ToolRegistry(self._state, self._state)
        self._pump_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._closed = False
        self._model_dispatch_task: asyncio.Task[None] | None = None
        self._model_activity_tasks: dict[asyncio.Task[None], str] = {}
        self._memory_tasks: set[asyncio.Task[None]] = set()
        self._wake = asyncio.Event()

    def bind_tool_executors(self, bindings: tuple[ToolExecutorBinding, ...]) -> None:
        catalog = self._tools.bind(bindings)
        self._state.install_capability_catalog(CapabilityCatalogSnapshot(catalog.capabilities))

    async def submit_amp(self, value: object) -> str:
        amp = AmpEnvelope.parse(value)
        if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
            raise ValueError(_Msg.RESERVED_EVENT_TYPE.format(amp_type=amp.payload.type))
        await self._state.submit_amp(amp)
        self._wake.set()
        return amp.header.message_id

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        async with self._pump_lock:
            recoveries = await self._tools.recover_pending()
            ingested = await self._state.ingest()
            admitted = await self._triage_inbox()
            result: PumpResult = await self._state.pump(max_turns)
            receipts = await self._tools.execute_pending()
            self._ensure_model_dispatcher()
            if self._memory_store is not None:
                for entry in self._state.completed_memory_entries():
                    task = asyncio.create_task(self._remember(entry), name=f"aurora-memory-{entry.task_id}")
                    self._memory_tasks.add(task)
                    task.add_done_callback(self._memory_tasks.discard)
            await self._state.finalize_terminal_tasks()
            response = asdict(
                PumpResult(
                    ingested_event_ids=(*ingested, *result.ingested_event_ids),
                    admitted_task_ids=admitted,
                    processed_message_ids=result.processed_message_ids,
                    failed_message_ids=result.failed_message_ids,
                )
            )
            response["tool_recovery_receipts_emitted"] = recoveries
            response["tool_receipts_emitted"] = receipts
            return response

    async def _remember(self, entry: MemoryEntry) -> None:
        assert self._memory_store is not None
        try:
            await asyncio.to_thread(self._memory_store.remember, entry)
        except Exception as error:
            logger.warning(
                "Memory remember failed task_id=%s error_type=%s",
                entry.task_id,
                type(error).__name__,
            )

    async def _triage_inbox(self) -> tuple[str, ...]:
        """到期批次直接创建入口 triage Task；模型判断走正常 Agent turn 链路。"""
        batches = await self._state.claim_triage_batches(self._state.limits.model_concurrency)
        if not batches:
            return ()
        created: list[str] = []
        for batch in batches:
            task_id = await self._state.create_triage_task(batch)
            if task_id is not None:
                created.append(task_id)
        return tuple(created)

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            if self._state.has_work():
                await self.pump()
                continue
            if self._state.has_pending_model_requests():
                self._ensure_model_dispatcher()
            self._wake.clear()
            delay = self._state.store.inbox_delay_seconds()
            timeout = self._idle_wait_seconds if delay is None else min(self._idle_wait_seconds, max(delay, 0.01))
            waiters = (asyncio.create_task(self._wake.wait()), asyncio.create_task(stop.wait()))
            try:
                await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in waiters:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)

    def _ensure_model_dispatcher(self) -> None:
        if self._model_dispatch_task is None or self._model_dispatch_task.done():
            self._model_dispatch_task = asyncio.create_task(self._dispatch_models(), name="aurora-model-activities")

    async def _dispatch_models(self) -> None:
        while True:
            activities = await self._state.claim_model_requests(self._state.limits.model_concurrency)
            if not activities:
                return
            tasks = []
            for activity in activities:
                task = asyncio.create_task(self._execute_model(activity), name=f"aurora-model-{activity.activity_id}")
                self._model_activity_tasks[task] = activity.task_id
                task.add_done_callback(self._model_activity_tasks.pop)
                tasks.append(task)
            await asyncio.gather(*tasks, return_exceptions=True)
            self._wake.set()

    async def _execute_model(self, activity: Any) -> None:
        task = self._state.get_task(activity.task_id)
        if task is None or task.terminal:
            return
        try:
            result = await self._model_provider.complete(ModelRequest.from_dict(activity.request))
        except asyncio.CancelledError:
            await self._state.complete_model(activity, None, "cancelled")
            raise
        except Exception as error:
            await self._state.complete_model(activity, None, f"{type(error).__name__}: {error}")
            return
        await self._state.complete_model(activity, result.to_dict(), None)

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
            if self._model_dispatch_task is not None:
                self._model_dispatch_task.cancel()
            for task in tuple(self._model_activity_tasks):
                task.cancel()
            pending: tuple[asyncio.Task[None], ...] = (*self._model_activity_tasks, *self._memory_tasks)
            if self._model_dispatch_task is not None:
                pending = (*pending, self._model_dispatch_task)
            await asyncio.gather(*pending, return_exceptions=True)
            self._state.shutdown()

    def status(self) -> dict[str, Any]:
        return {
            **self._state.status(),
            "model_dispatch_active": self._model_dispatch_task is not None and not self._model_dispatch_task.done(),
            "active_model_activities": len(self._model_activity_tasks),
        }

    def task_detail(self, task_id: str) -> dict[str, Any] | None:
        return self._state.task_detail(task_id)

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        return self._state.agent_detail(agent_id)

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage:
        """返回游标之后新增的用户可见模型输出（只读）。"""
        return self._state.output_stream(cursor, limit=limit)
