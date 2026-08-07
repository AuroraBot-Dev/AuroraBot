"""完整拥有 Agent pump 热路径的运行时引擎。

AgentEngine 是外部可见的唯一入口——组合持久化状态、模型、工具与自动记忆服务。
EngineState 拥有 Task/Agent 持久化状态、邮箱队列和 Activity 调度，
将所有认知决策委托给外部 Agent handler，将 I/O 委托给平台层。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from jsonschema import ValidationError, validate

from src.contracts.agent import (
    ActivityRequest,
    AgentContext,
    AgentDecision,
    AgentHandler,
    AgentInstance,
    AgentLimits,
    AgentProfile,
    CapabilityCatalogSnapshot,
    DelegationRequest,
    EngineConfiguration,
    TaskState,
    TaskStatus,
    ToolLease,
    ToolRequest,
    capability_tool_definition,
)
from src.contracts.amp import AmpEnvelope, AmpValidationError
from src.contracts.event import OutputStreamItem, OutputStreamPage
from src.contracts.memory import MemoryContextSnapshot, MemoryEntry, MemoryQuery
from src.contracts.model import ModelRequest
from src.contracts.triage import TriageAction, TriageBatch, TriageDecision
from src.engine.archive import (
    TASK_ARCHIVE_VERSION,
    archived_agent_detail,
    read_task_archive,
    task_archive_projection,
)
from src.engine.debug import agent_detail as build_agent_detail
from src.engine.debug import reject_active_legacy_workspace
from src.engine.debug import task_detail as build_task_detail
from src.engine.session_log import SessionLog
from src.engine.store import SQLiteRuntimeStore
from src.engine.tool_registry import ToolRegistry
from src.utils.logging import get_logger
from src.utils.serialization import atomic_write_json, read_json

if TYPE_CHECKING:
    from src.contracts.memory import MemoryStore
    from src.contracts.model import ModelProvider
    from src.contracts.tool import ToolExecutorBinding
    from src.contracts.triage import TriagePolicy

logger = get_logger("aurora.engine")
_TRIAGE_SUMMARY_LIMIT = 600


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    RESERVED_EVENT_TYPE = "reserved internal event type: {amp_type}"
    RESERVED_TOOL_EVENT = "Tool receipt event types are reserved for internal Runtime use"
    HANDLERS_MISMATCH = "Agent handlers must exactly match configured profiles"
    ROOT_PROFILE_MISSING = "root Agent profile is not configured"
    CATALOG_ALREADY_INSTALLED = "capability catalog is already installed"
    MAX_TURNS_POSITIVE = "max_turns must be positive"
    INVALID_TOOL_OUTCOME = "invalid Tool outcome"
    TOOL_COMPLETION_UNMATCHED = "Tool completion does not match an active request: {request_id}"
    AGENT_MODEL_ROLE_DENIED = "Agent {agent_id} cannot request model role {role}"
    AGENT_TOOL_DENIED = "Agent {agent_id} cannot request {capability}"
    UNKNOWN_TOOL = "unknown Tool capability {capability}"
    TOOL_PARAMS_MISMATCH = "Tool parameters do not match {capability}: {message}"
    PROFILE_CANNOT_DELEGATE = "Agent profile {profile_id} cannot delegate"
    PROFILE_CANNOT_CREATE = "Agent profile {profile_id} cannot create {child_profile}"
    TRIAGE_FALLBACK_REASON = "fail-open:{error_type}"
    TRIAGE_FALLBACK_SUMMARY = "Inbox event batch"


# -- 类型与工具函数 ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PumpResult:
    ingested_event_ids: tuple[str, ...]
    admitted_task_ids: tuple[str, ...]
    processed_message_ids: tuple[str, ...]
    failed_message_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -- 决策处理 ------------------------------------------------------------


def _capability_allowed(capability: str, policies: frozenset[str]) -> bool:
    return (
        "*" in policies
        or capability in policies
        or any(policy.endswith(".*") and capability.startswith(policy[:-1]) for policy in policies)
    )


def _build_limit_dict(limits: AgentLimits) -> dict[str, Any]:
    return {
        "max_active_agents": limits.max_active_agents,
        "max_agents_per_task": limits.max_agents_per_task,
        "max_depth": limits.max_depth,
        "max_children_per_agent": limits.max_children_per_agent,
        "worker_profile": limits.worker_profile,
    }


class DecisionRuntime(Protocol):
    _profiles: dict[str, AgentProfile]
    _handlers: dict[str, AgentHandler]
    store: SQLiteRuntimeStore

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...

    def recall_memory(self, query: MemoryQuery) -> MemoryContextSnapshot: ...


def handle_claim(kernel: DecisionRuntime, claim: tuple[Any, AgentInstance, TaskState]) -> tuple[AgentDecision, str]:
    """构造只读 AgentContext 并调用对应 handler，返回 (决策, 授权的 profile_id)。

    task/agent/message/children 直接复用当轮新建的 store 对象，不做深拷贝；
    handler 违反只读契约的变异会以乐观锁冲突失败，不会静默损坏状态。
    profile 与 capability 描述符是跨轮共享的规范对象，必须拷贝，防止 handler
    通过变异 context 提权。返回的 profile_id 在 handler 运行前捕获，apply
    路径据此取规范 profile，篡改 agent.profile_id 无法重定向授权。
    """
    message, agent, task = claim
    profile_id = agent.profile_id
    profile = deepcopy(kernel._profiles[profile_id])
    descriptors = deepcopy(
        tuple(
            descriptor
            for descriptor in kernel.capability_catalog.capabilities
            if _capability_allowed(descriptor.id, profile.capabilities)
        )
    )
    context = AgentContext(
        task=task,
        agent=agent,
        message=message,
        children=kernel.store.children(agent.agent_id),
        profile=profile,
        capabilities=descriptors,
        tool_definitions=tuple(capability_tool_definition(item) for item in descriptors),
        memory=kernel.recall_memory(MemoryQuery(task.root_summary, task.session_id)),
        pending_child_reports=kernel.store.has_pending_child_reports(agent.agent_id),
    )
    return kernel._handlers[profile_id].handle(context), profile_id


def apply_failure(kernel: DecisionRuntime, message: Any, agent: AgentInstance, error: str) -> None:
    kernel.store.apply_decision(
        message=message,
        agent=agent,
        decision=AgentDecision(failure=error),
        state_patch={},
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def apply_authorized_decision(
    kernel: DecisionRuntime, message: Any, agent: AgentInstance, profile_id: str, decision: AgentDecision
) -> None:
    """按决策字段分派授权校验；校验通过后原样交给 store 原子执行（RFC 0205）。

    completion/wait/failure 无需额外授权；wait 的等待前提校验在 store
    事务内原子完成。所有 resource 上界校验仍由 store 事务内执行。
    """
    profile = kernel._profiles[profile_id]
    if decision.model_request is not None:
        _authorize_model(agent, profile, decision.model_request)
    elif decision.tool_request is not None:
        _authorize_tool(kernel, agent, profile, decision.tool_request)
    elif decision.delegations:
        _authorize_delegation(kernel, profile, decision.delegations)
    kernel.store.apply_decision(
        message=message,
        agent=agent,
        decision=decision,
        state_patch=decision.state_patch,
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def _authorize_model(agent: AgentInstance, profile: AgentProfile, request: ModelRequest) -> None:
    if request.role != profile.model_role:
        raise PermissionError(_Msg.AGENT_MODEL_ROLE_DENIED.format(agent_id=agent.agent_id, role=request.role))


def _authorize_tool(kernel: DecisionRuntime, agent: AgentInstance, profile: AgentProfile, tool: ToolRequest) -> None:
    if not _capability_allowed(tool.capability, profile.capabilities):
        raise PermissionError(_Msg.AGENT_TOOL_DENIED.format(agent_id=agent.agent_id, capability=tool.capability))
    descriptor = kernel.capability_catalog.by_id.get(tool.capability)
    if descriptor is None:
        raise ValueError(_Msg.UNKNOWN_TOOL.format(capability=tool.capability))
    try:
        validate(tool.parameters, descriptor.parameters_schema)
    except ValidationError as error:
        raise ValueError(_Msg.TOOL_PARAMS_MISMATCH.format(capability=tool.capability, message=error.message)) from error


def _authorize_delegation(
    kernel: DecisionRuntime, profile: AgentProfile, delegations: tuple[DelegationRequest, ...]
) -> None:
    if not profile.can_delegate:
        raise PermissionError(_Msg.PROFILE_CANNOT_DELEGATE.format(profile_id=profile.id))
    for delegation in delegations:
        child_profile = delegation.profile_id or kernel.limits.worker_profile
        if child_profile not in profile.child_profiles or child_profile not in kernel._profiles:
            raise PermissionError(_Msg.PROFILE_CANNOT_CREATE.format(profile_id=profile.id, child_profile=child_profile))


# -- AMP 摄入 ------------------------------------------------------------


class IngressRuntime(Protocol):
    configuration: EngineConfiguration
    store: SQLiteRuntimeStore
    _inbox: Path
    _archive: Path
    _session_log: SessionLog
    _profiles: dict[str, AgentProfile]

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...


def ingest_ready(kernel: IngressRuntime) -> tuple[str, ...]:
    ingested: list[str] = []
    for p in sorted(kernel._inbox.glob("*.json")):
        try:
            amp = AmpEnvelope.parse(read_json(p))
        except (OSError, ValueError, TypeError, AmpValidationError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", p.name, error)
            _archive_inbox(kernel, p, "rejected")
            continue
        try:
            _ingest_amp_file(kernel, amp, p, ingested)
        except (ValueError, TypeError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", p.name, error)
            _archive_inbox(kernel, p, "rejected")
    return tuple(ingested)


def _ingest_amp(kernel: IngressRuntime, amp: AmpEnvelope, ingested: list[str]) -> None:
    if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
        raise ValueError(_Msg.RESERVED_TOOL_EVENT)
    if kernel.store.enqueue_inbox(amp, kernel.configuration.triage):
        kernel._session_log.amp_in(amp)
        ingested.append(amp.header.message_id)


def persist_amp(kernel: IngressRuntime, amp: AmpEnvelope) -> bool:
    """在入口回执前将单个 AMP 幂等写入持久化 Inbox。"""
    ingested: list[str] = []
    _ingest_amp(kernel, amp, ingested)
    return bool(ingested)


def _ingest_amp_file(kernel: IngressRuntime, amp: AmpEnvelope, path: Path, ingested: list[str]) -> None:
    before = len(ingested)
    _ingest_amp(kernel, amp, ingested)
    if len(ingested) > before:
        _archive_inbox(kernel, path, "accepted")
    else:
        _archive_inbox(kernel, path, "duplicate")


def _archive_inbox(kernel: IngressRuntime, source: Path, category: str) -> None:
    destination_dir = kernel._archive / "inbox" / category
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
    source.replace(destination)


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
        events = self.store.events_for_task(task_id)
        if not events:
            return ()
        triage = events[0].get("payload", {}).get("triage")
        candidate = triage.get("memory_candidate") if isinstance(triage, dict) else None
        return (candidate,) if isinstance(candidate, str) and candidate.strip() else ()

    async def ingest(self) -> tuple[str, ...]:
        """只把 AMP 写入持久化 Inbox，不创建 Task。"""
        async with self._lock:
            return await self._store_call(self._ingest_ready)

    async def claim_triage_batches(self, limit: int) -> tuple[TriageBatch, ...]:
        return await self._store_call(self.store.claim_triage_batches, self.configuration.triage, limit)

    async def apply_triage(self, batch: TriageBatch, decision: TriageDecision) -> str | None:
        priority = max((event.priority for event in batch.events), default=100)
        task_id = await self._store_call(
            self.store.apply_triage,
            batch,
            decision,
            root_profile=self.limits.root_profile,
            interactive_budget=self.configuration.interactive_budget,
            autonomous_budget=self.configuration.autonomous_budget,
            priority=priority,
        )
        if task_id is not None:
            self._session_log.task_admitted(task_id, batch.session_id, decision.summary)
        return task_id

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
                    "SELECT 1 FROM activities WHERE kind = 'model' AND status = 'PENDING' LIMIT 1"
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
        triage_policy: TriagePolicy,
        tool_registry: ToolRegistry | None = None,
        memory_store: MemoryStore | None = None,
        idle_wait_seconds: float = 1.0,
    ) -> None:
        self.configuration = configuration
        self._state = EngineState(configuration, handlers, memory_store)
        self._model_provider = model_provider
        self._triage_policy = triage_policy
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
        batches = await self._state.claim_triage_batches(self._state.limits.model_concurrency)
        if not batches:
            return ()
        results = await asyncio.gather(
            *(self._triage_batch(batch) for batch in batches),
            return_exceptions=True,
        )
        admitted: list[str] = []
        for batch, result in zip(batches, results, strict=True):
            decision = result if isinstance(result, TriageDecision) else self._triage_fallback(batch, result)
            task_id = await self._state.apply_triage(batch, decision)
            if task_id is not None:
                admitted.append(task_id)
        return tuple(admitted)

    async def _triage_batch(self, batch: TriageBatch) -> TriageDecision:
        request = self._triage_policy.request(batch)
        result = await self._model_provider.complete(request)
        return self._triage_policy.resolve(batch, result)

    @staticmethod
    def _triage_fallback(batch: TriageBatch, error: object) -> TriageDecision:
        logger.warning(
            "Triage failed; admitting batch batch_id=%s error_type=%s",
            batch.batch_id,
            type(error).__name__,
        )
        summary = "；".join(event.summary for event in batch.events)
        if len(summary) > _TRIAGE_SUMMARY_LIMIT:
            summary = summary[: _TRIAGE_SUMMARY_LIMIT - 1] + "…"
        return TriageDecision(
            action=TriageAction.PROCESS,
            summary=summary or _Msg.TRIAGE_FALLBACK_SUMMARY,
            reason=_Msg.TRIAGE_FALLBACK_REASON.format(error_type=type(error).__name__),
        )

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

    def brain_context(self) -> dict[str, Any]:
        """返回紧凑运行态计数；该投影不会进入模型上下文。"""
        return self.status()
