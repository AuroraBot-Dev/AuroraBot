"""AgentEngine — 单进程 asyncio 独占的完整 Agent 运行时。

单一存储（SQLite v10 即归档）、无租约无乐观锁。store 与纯 handler 由单一
事件循环串行拥有；模型、工具与记忆 Port 使用 async，记忆实现把阻塞 I/O
委派到受控工作线程。终态 Task 留在 SQLite，不做文件归档。
"""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.contracts import (
    ActivityRequest,
    AgentHandler,
    AgentInstance,
    AgentLimits,
    AgentMessage,
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
    TriageBatch,
)
from src.engine.authorize import apply_authorized_decision, apply_failure, handle_claim
from src.engine.debug import agent_detail as build_agent_detail
from src.engine.debug import reject_active_legacy_workspace
from src.engine.debug import task_detail as build_task_detail
from src.engine.ingress import persist_amp
from src.engine.store import SQLiteRuntimeStore
from src.engine.tool_registry import ToolRegistry
from src.utils import get_logger, utc_now

logger = get_logger("aurora.engine")

if TYPE_CHECKING:
    from src.contracts.memory import MemoryStore
    from src.contracts.model import ModelProvider
    from src.contracts.tool import ToolExecutorBinding


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    RESERVED_EVENT_TYPE = "reserved internal event type: {amp_type}"
    HANDLERS_MISMATCH = "Agent handlers must exactly match configured profiles"
    ROOT_PROFILE_MISSING = "root Agent profile is not configured"
    MAX_TURNS_POSITIVE = "max_turns must be positive"
    INVALID_TOOL_OUTCOME = "invalid Tool outcome"
    TOOL_COMPLETION_UNMATCHED = "Tool completion does not match an active request: {request_id}"


def _memory_turn_input(message: AgentMessage) -> str:
    """从消息投影提取记忆窗口的 user 侧文本。"""
    payload = message.payload
    for key in ("batch", "context_events"):
        container = payload.get(key)
        if isinstance(container, dict):
            container = container.get("events")
        if isinstance(container, list):
            summaries = [
                str(item.get("summary", "")) for item in container if isinstance(item, dict) and item.get("summary")
            ]
            if summaries:
                return "；".join(summaries)
    if isinstance(payload.get("instruction"), str):
        return payload["instruction"]
    if message.type.startswith("tool."):
        request = payload.get("request")
        if isinstance(request, dict):
            return f"{message.type}: {request.get('parameters', {})}"
        return message.type
    if isinstance(payload.get("summary"), str) and payload["summary"].strip():
        return payload["summary"]
    return message.type


class AgentEngine:
    """组合持久化状态、模型、工具与自动记忆服务的完整 Agent 引擎。"""

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
        self._profiles = {profile.id: profile for profile in configuration.profiles}
        if set(self._profiles) != set(handlers):
            raise ValueError(_Msg.HANDLERS_MISMATCH)
        if configuration.limits.root_profile not in self._profiles:
            raise ValueError(_Msg.ROOT_PROFILE_MISSING)
        self._handlers = handlers
        self._model_provider = model_provider
        self._memory_store = memory_store
        self._idle_wait_seconds = idle_wait_seconds
        self._workspace = Path(configuration.workspace)
        reject_active_legacy_workspace(self._workspace)
        self.store = SQLiteRuntimeStore(self._workspace / "runtime.sqlite3")
        self.store.initialize()
        self._tools = tool_registry if tool_registry is not None else ToolRegistry(self.store)
        self._capability_catalog: CapabilityCatalogSnapshot | None = None
        self._pump_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._closed = False
        self._model_dispatch_task: asyncio.Task[None] | None = None
        self._model_activity_tasks: dict[asyncio.Task[None], str] = {}
        self._model_dispatch_wake = asyncio.Event()
        self._tool_dispatch_task: asyncio.Task[None] | None = None
        self._tool_dispatch_wake = asyncio.Event()
        self._tools_recovered = False
        self._memory_tasks: set[asyncio.Task[None]] = set()
        self._wake = asyncio.Event()
        logger.info(
            "Agent engine initialized workspace=%s profiles=%d active_tasks=%d",
            self._workspace,
            len(self._profiles),
            self.store.counts()["active_tasks"],
        )

    # -- 配置与能力目录 ---------------------------------------------------

    @property
    def limits(self) -> AgentLimits:
        return self.configuration.limits

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        return self._capability_catalog or CapabilityCatalogSnapshot()

    def install_capability_catalog(self, catalog: CapabilityCatalogSnapshot) -> None:
        self._capability_catalog = catalog

    def bind_tool_executors(self, bindings: tuple[ToolExecutorBinding, ...]) -> None:
        catalog = self._tools.bind(bindings)
        self.install_capability_catalog(CapabilityCatalogSnapshot(catalog.capabilities))

    # -- 记忆（被动服务）--------------------------------------------------

    async def recall_memory(self, query: MemoryQuery) -> MemoryContextSnapshot:
        if self._memory_store is None:
            return MemoryContextSnapshot()
        try:
            return await self._memory_store.recall(query)
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

    # -- 摄入 -------------------------------------------------------------

    async def submit_amp(self, value: object) -> str:
        amp = AmpEnvelope.parse(value)
        if persist_amp(self, amp):
            superseded = self.store.supersede_session_generation(amp, self.configuration.triage)
            self._cancel_model_activities(superseded)
        self._wake.set()
        return amp.header.message_id

    def consume_tool_receipt(self, amp: AmpEnvelope) -> None:
        """工具回执 AMP：校验并交给 store 幂等消费。"""
        status = amp.payload.type.removeprefix("tool.")
        data = amp.payload.data
        request_id = data.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError(_Msg.INVALID_TOOL_OUTCOME)
        capability = data.get("capability")
        if not isinstance(capability, str) or not capability:
            raise ValueError(_Msg.INVALID_TOOL_OUTCOME)
        error = data.get("error")
        result = data.get("result")
        if (status == "succeeded" and error is not None) or (
            status != "succeeded" and (not error or result is not None)
        ):
            raise ValueError(_Msg.INVALID_TOOL_OUTCOME)
        self.store.consume_tool_receipt(
            request_id=request_id,
            event_type=amp.payload.type,
            summary=amp.payload.summary,
            payload={
                "request_id": request_id,
                "capability": capability,
                "result": result,
                "error": error,
                "source": amp.header.source,
            },
        )

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        async with self._pump_lock:
            admitted = self._triage_inbox()
            expired = self.store.expire_tasks()
            processed, failed = await self._pump_turns(max_turns)
            self._ensure_model_dispatcher()
            self._ensure_tool_dispatcher()
            self._project_memory()
            # 让出控制权：后台模型/工具派发任务依赖事件循环调度，pump 无消息可
            # 处理时若不让出，has_work 自旋会饿死派发任务与 console/平台任务
            await asyncio.sleep(0)
            return {
                "admitted_task_ids": admitted,
                "expired_task_ids": expired,
                "processed_message_ids": processed,
                "failed_message_ids": failed,
                "model_dispatch_active": self._model_dispatch_task is not None,
                "tool_dispatch_active": self._tool_dispatch_task is not None,
            }

    def _triage_inbox(self) -> tuple[str, ...]:
        """到期批次创建入口 triage Task；模型判断走正常 Agent turn 链路。"""
        batches = self.store.claim_triage_batches(self.configuration.triage, self.limits.model_concurrency)
        created: list[str] = []
        for batch in batches:
            task_id = self._create_triage_task(batch)
            if task_id is not None:
                created.append(task_id)
        return tuple(created)

    def _create_triage_task(self, batch: TriageBatch) -> str | None:
        priority = max((event.priority for event in batch.events), default=100)
        created = self.store.create_triage_task(
            batch,
            triage_profile=self.limits.root_profile,
            interactive_budget=self.configuration.interactive_budget,
            autonomous_budget=self.configuration.autonomous_budget,
            priority=priority,
        )
        return created[0] if created is not None else None

    async def _pump_turns(self, max_turns: int | None) -> tuple[list[str], list[str]]:
        limit = self.limits.turn_concurrency if max_turns is None else max_turns
        if limit <= 0:
            raise ValueError(_Msg.MAX_TURNS_POSITIVE)
        processed: list[str] = []
        failed: list[str] = []
        for _ in range(limit):
            claim = self.store.claim_message()
            if claim is None:
                break
            message, agent, task = claim
            try:
                await self._append_memory_turn(task.session_id, "user", _memory_turn_input(message))
                memory = await self.recall_memory(MemoryQuery(task.root_summary, task.session_id))
                decision, profile_id = handle_claim(self, message, agent, task, memory)
                apply_authorized_decision(self, message, agent, profile_id, decision)
                if decision.completion is not None:
                    await self._append_memory_turn(task.session_id, "assistant", decision.completion.summary)
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
                    apply_failure(self, message, agent, f"{type(error).__name__}: {error}")
                except Exception:
                    self.store.fail_message(message.message_id, str(error))
                failed.append(message.message_id)
        return processed, failed

    async def _append_memory_turn(self, scope: str, role: str, content: str) -> None:
        """记录一轮对话到记忆窗口（短期历史）。"""
        if self._memory_store is None or not content.strip():
            return
        await self._memory_store.append_turn(
            scope,
            role=role,
            content=content,
            at=utc_now(),
        )

    def _project_memory(self) -> None:
        if self._memory_store is None:
            return
        for entry in self.completed_memory_entries():
            task = asyncio.create_task(self._remember(entry), name=f"aurora-memory-{entry.task_id}")
            self._memory_tasks.add(task)
            task.add_done_callback(self._memory_tasks.discard)

    async def _remember(self, entry: MemoryEntry) -> None:
        assert self._memory_store is not None
        try:
            await self._memory_store.remember(entry)
        except Exception as error:
            logger.warning("Memory remember failed task_id=%s error_type=%s", entry.task_id, type(error).__name__)

    # -- 模型派发 ---------------------------------------------------------

    def _ensure_model_dispatcher(self) -> None:
        self._model_dispatch_wake.set()
        if self._model_dispatch_task is None or self._model_dispatch_task.done():
            self._model_dispatch_task = asyncio.create_task(self._dispatch_models(), name="aurora-model-activities")

    async def _dispatch_models(self) -> None:
        running: set[asyncio.Task[None]] = set()
        while True:
            self._model_dispatch_wake.clear()
            capacity = self.limits.model_concurrency - len(running)
            for row in self.store.claim_activities("model", capacity) if capacity > 0 else ():
                activity = self.store._activity(row)
                task = asyncio.create_task(self._execute_model(activity), name=f"aurora-model-{activity.activity_id}")
                self._model_activity_tasks[task] = activity.activity_id
                task.add_done_callback(self._model_activity_tasks.pop)
                running.add(task)
            if not running:
                return
            wake_task: asyncio.Task[bool] | None = None
            waiters: set[asyncio.Task[Any]] = set(running)
            if len(running) < self.limits.model_concurrency:
                wake_task = asyncio.create_task(self._model_dispatch_wake.wait())
                waiters.add(wake_task)
            done, _pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            completed = done & running
            running.difference_update(completed)
            if wake_task is not None and not wake_task.done():
                wake_task.cancel()
                await asyncio.gather(wake_task, return_exceptions=True)
            if completed:
                await asyncio.gather(*completed, return_exceptions=True)
            self._wake.set()

    def _ensure_tool_dispatcher(self) -> None:
        self._tool_dispatch_wake.set()
        if self._tool_dispatch_task is None or self._tool_dispatch_task.done():
            self._tool_dispatch_task = asyncio.create_task(self._dispatch_tools(), name="aurora-tool-activities")

    async def _dispatch_tools(self) -> None:
        await self._tools.execute_pending(
            self.limits.tool_concurrency,
            wake=self._tool_dispatch_wake,
            recover=not self._tools_recovered,
        )
        self._tools_recovered = True
        self._wake.set()

    def _cancel_model_activities(self, activity_ids: tuple[str, ...]) -> None:
        targets = set(activity_ids)
        for task, activity_id in tuple(self._model_activity_tasks.items()):
            if activity_id in targets and not task.done():
                task.cancel()

    async def _execute_model(self, activity: ActivityRequest) -> None:
        task = self.store.get_task(activity.task_id)
        if task is None or task.terminal:
            return
        try:
            result = await self._model_provider.complete(ModelRequest.from_dict(activity.request))
        except asyncio.CancelledError:
            self.store.complete_model_activity(activity.activity_id, None, "cancelled")
            raise
        except Exception as error:
            self.store.complete_model_activity(activity.activity_id, None, f"{type(error).__name__}: {error}")
            return
        self.store.complete_model_activity(activity.activity_id, result.to_dict(), None)

    # -- 查询代理 ---------------------------------------------------------

    def tasks(self) -> tuple[TaskState, ...]:
        return self.store.tasks()

    def get_task(self, task_id: str) -> TaskState | None:
        return self.store.get_task(task_id)

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        return self.store.get_agent(agent_id)

    def task_detail(self, task_id: str) -> dict[str, Any] | None:
        return build_task_detail(self.store, task_id)

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        return build_agent_detail(self.store, agent_id)

    def status(self) -> dict[str, Any]:
        return {
            **self.store.counts(),
            "model_dispatch_active": self._model_dispatch_task is not None and not self._model_dispatch_task.done(),
            "active_model_activities": len(self._model_activity_tasks),
            "tool_dispatch_active": self._tool_dispatch_task is not None and not self._tool_dispatch_task.done(),
        }

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage:
        """返回游标之后新增的用户可见模型输出（只读）。"""
        rows = self.store.recent_outputs(cursor, limit=limit)
        items = tuple(OutputStreamItem(**row) for row in rows)
        next_cursor = items[-1].cursor if items else cursor
        return OutputStreamPage(items=items, next_cursor=next_cursor)

    def output_tail_cursor(self) -> int:
        """当前输出流末尾游标：新前端从该游标起订阅，避免重放历史。"""
        return self.store.recent_outputs_tail()

    def list_tasks(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        """Task 列表投影（观察操作）。"""
        rows = self.store.tasks(status=status, limit=limit)
        return [row.to_dict() for row in rows]

    def list_agents(self, *, limit: int = 64) -> list[dict[str, Any]]:
        """Agent 列表投影。"""
        return [row.to_dict() for row in self.store.agents(limit=limit)]

    def query_events(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        event_type: str | None = None,
        after_id: int = 0,
        limit: int = 64,
    ) -> list[dict[str, Any]]:
        """因果事件流查询（观察操作）。"""
        return list(
            self.store.query_events(
                session_id=session_id, task_id=task_id, event_type=event_type, after_id=after_id, limit=limit
            )
        )

    def session_export(self, session_id: str) -> dict[str, Any] | None:
        """会话导出：因果事件与模型输出投影。"""
        return self.store.session_export(session_id)

    def has_work(self) -> bool:
        counts = self.store.counts()
        return (
            self.store.has_due_inbox()
            or counts["pending_messages"] > 0
            or self.store.has_claimable_external_activity(self.limits.tool_concurrency)
            or self.store.has_recoverable_tool()
        )

    def cancel_task(self, task_id: str, reason: str) -> None:
        self._cancel_model_activities(self.store.cancel_task(task_id, reason))

    # -- 生命周期 ---------------------------------------------------------

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            if self.has_work():
                await self.pump()
                continue
            if self.store.counts()["pending_model_activities"] > 0:
                self._ensure_model_dispatcher()
            self._wake.clear()
            delay = self.store.inbox_delay_seconds()
            timeout = self._idle_wait_seconds if delay is None else min(self._idle_wait_seconds, max(delay, 0.01))
            waiters = (asyncio.create_task(self._wake.wait()), asyncio.create_task(stop.wait()))
            try:
                await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in waiters:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
            if self._model_dispatch_task is not None:
                self._model_dispatch_task.cancel()
            if self._tool_dispatch_task is not None:
                self._tool_dispatch_task.cancel()
            for task in tuple(self._model_activity_tasks):
                task.cancel()
            pending: tuple[asyncio.Task[None], ...] = (*self._model_activity_tasks, *self._memory_tasks)
            if self._model_dispatch_task is not None:
                pending = (*pending, self._model_dispatch_task)
            if self._tool_dispatch_task is not None:
                pending = (*pending, self._tool_dispatch_task)
            loop = asyncio.get_running_loop()
            current = [task for task in pending if task.get_loop() is loop]
            await asyncio.gather(*current, return_exceptions=True)
