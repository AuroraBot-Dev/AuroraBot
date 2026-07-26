"""完整拥有 Agent pump 热路径的运行时引擎。

AgentEngine 是外部可见的唯一入口——组合持久化状态、模型、工具与自动记忆服务。
EngineState 拥有 Task/Agent 持久化状态、邮箱队列和 Activity 调度，
将所有认知决策委托给外部 Agent handler，将 I/O 委托给平台层。
"""

from __future__ import annotations

import asyncio
import contextlib
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
    BrainContextSnapshot,
    CapabilityCatalogSnapshot,
    EngineConfiguration,
    TaskState,
    TaskStatus,
    ToolLease,
)
from src.contracts.amp import AmpEnvelope, AmpValidationError
from src.contracts.memory import MemoryContextSnapshot, MemoryEntry
from src.contracts.model import ModelRequest
from src.engine.commands import (
    CompleteCommand,
    DelegateCommand,
    FailCommand,
    ModelCommand,
    ToolCommand,
    WaitCommand,
)
from src.engine.debug import agent_detail as build_agent_detail
from src.engine.debug import reject_active_legacy_workspace
from src.engine.debug import task_detail as build_task_detail
from src.engine.store import SQLiteRuntimeStore, utc_now
from src.engine.tool_registry import ToolRegistry
from src.utils.logging import get_logger
from src.utils.serialization import atomic_write_json, read_json

if TYPE_CHECKING:
    from src.contracts.memory import MemoryStore
    from src.contracts.model import ModelProvider
    from src.contracts.tool import ToolExecutorBinding

logger = get_logger("aurora.engine")


class _Msg(StrEnum):
    RESERVED_EVENT_TYPE = "reserved internal event type: {amp_type}"
    RESERVED_TOOL_EVENT = "Tool receipt event types are reserved for internal Runtime use"
    HANDLERS_MISMATCH = "Agent handlers must exactly match configured profiles"
    ROOT_PROFILE_MISSING = "root Agent profile is not configured"
    CATALOG_ALREADY_INSTALLED = "capability catalog is already installed"
    MAX_TURNS_POSITIVE = "max_turns must be positive"
    INVALID_TOOL_OUTCOME = "invalid Tool outcome"
    TOOL_COMPLETION_UNMATCHED = "Tool completion does not match an active request: {request_id}"
    UNSUPPORTED_DECISION = "unsupported Agent decision"
    AGENT_MODEL_ROLE_DENIED = "Agent {agent_id} cannot request model role {role}"
    AGENT_TOOL_DENIED = "Agent {agent_id} cannot request {capability}"
    UNKNOWN_TOOL = "unknown Tool capability {capability}"
    TOOL_PARAMS_MISMATCH = "Tool parameters do not match {capability}: {message}"
    PROFILE_CANNOT_DELEGATE = "Agent profile {profile_id} cannot delegate"
    PROFILE_CANNOT_CREATE = "Agent profile {profile_id} cannot create {child_profile}"
    WAIT_WITHOUT_CHILDREN = "Agent cannot wait without active children"


# -- 类型与工具函数 ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PumpResult:
    ingested_task_ids: tuple[str, ...]
    processed_message_ids: tuple[str, ...]
    failed_message_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_brain_context(store: SQLiteRuntimeStore) -> BrainContextSnapshot:
    tasks = store.tasks(active_only=True)
    agents = store.agents(active_only=True)
    task_projections: list[dict[str, Any]] = []
    for task in tasks:
        events = store.events_for_task(task.task_id)
        projection: dict[str, Any] = {
            "task_id": task.task_id,
            "status": task.status,
            "model_calls": task.model_calls,
            "tool_calls": task.tool_calls,
            "max_model_calls": task.max_model_calls,
            "max_tool_calls": task.max_tool_calls,
            "work_type": "autonomous" if task.autonomous else "interactive",
            "updated_at": task.updated_at,
            "session_id": task.session_id,
            "summary": task.root_summary,
            "latest_activity": events[-1]["summary"] if events else task.root_summary,
        }
        task_projections.append(projection)
    agent_projections: list[dict[str, Any]] = []
    for agent in agents:
        projection = {
            "agent_id": agent.agent_id,
            "task_id": agent.task_id,
            "parent_agent_id": agent.parent_agent_id,
            "profile_id": agent.profile_id,
            "status": agent.status,
            "updated_at": agent.updated_at,
        }
        projection.update({"assignment": agent.assignment, "last_summary": agent.last_summary})
        agent_projections.append(projection)
    situations = store.situations()
    return BrainContextSnapshot(
        active_tasks=tuple(task_projections),
        active_agents=tuple(agent_projections),
        ambient_situations=situations,
        generated_at=utc_now(),
    )


# -- 决策处理 ------------------------------------------------------------


def _capability_allowed(capability: str, policies: frozenset[str]) -> bool:
    return (
        "*" in policies
        or capability in policies
        or any(policy.endswith(".*") and capability.startswith(policy[:-1]) for policy in policies)
    )


def _build_limit_dict(limits: AgentLimits) -> dict[str, int]:
    return {
        "max_active_agents": limits.max_active_agents,
        "max_agents_per_task": limits.max_agents_per_task,
        "max_depth": limits.max_depth,
        "max_children_per_agent": limits.max_children_per_agent,
    }


class DecisionRuntime(Protocol):
    _profiles: dict[str, AgentProfile]
    _handlers: dict[str, AgentHandler]
    store: SQLiteRuntimeStore

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...

    def brain_context(self) -> BrainContextSnapshot: ...

    def recall_memory(self, query: str) -> MemoryContextSnapshot: ...


def handle_claim(kernel: DecisionRuntime, claim: tuple[Any, AgentInstance, TaskState]) -> AgentDecision:
    message, agent, task = claim
    profile = kernel._profiles[agent.profile_id]
    descriptors = tuple(
        descriptor
        for descriptor in kernel.capability_catalog.capabilities
        if _capability_allowed(descriptor.id, profile.capabilities)
    )
    context = AgentContext(
        task=deepcopy(task),
        agent=deepcopy(agent),
        message=deepcopy(message),
        children=deepcopy(kernel.store.children(agent.agent_id)),
        profile=deepcopy(profile),
        capabilities=deepcopy(descriptors),
        brain=deepcopy(kernel.brain_context()),
        memory=kernel.recall_memory(task.root_summary),
    )
    return kernel._handlers[agent.profile_id].handle(context)


def apply_failure(kernel: DecisionRuntime, message: Any, agent: AgentInstance, error: str) -> None:
    command = FailCommand(summary=error, error=error)
    kernel.store.apply_decision(
        message=message,
        agent=agent,
        command=command,
        state_patch={},
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def apply_authorized_decision(
    kernel: DecisionRuntime, message: Any, agent: AgentInstance, decision: AgentDecision
) -> None:
    profile = kernel._profiles[agent.profile_id]
    claims = tuple(decision.claims)
    if decision.model_request is not None:
        command = _apply_model_request(kernel, agent, decision, profile, claims)
    elif decision.tool_request is not None:
        command = _apply_tool_request(kernel, agent, decision, profile, claims)
    elif decision.delegations:
        command = _apply_delegations(kernel, agent, decision, profile, claims)
    elif decision.completion is not None:
        command = _apply_completion(decision, claims)
    elif decision.wait_for_children:
        command = _apply_wait(kernel, agent, claims)
    elif decision.failure is not None:
        command = _apply_failure(decision, claims)
    else:
        raise ValueError(_Msg.UNSUPPORTED_DECISION)
    kernel.store.apply_decision(
        message=message,
        agent=agent,
        command=command,
        state_patch=decision.state_patch,
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def _apply_model_request(
    _kernel: DecisionRuntime,
    agent: AgentInstance,
    decision: AgentDecision,
    profile: AgentProfile,
    claims: tuple[Any, ...],
) -> ModelCommand:
    request_role = decision.model_request.get("role")  # type: ignore[union-attr]
    if request_role != profile.model_role:
        raise PermissionError(_Msg.AGENT_MODEL_ROLE_DENIED.format(agent_id=agent.agent_id, role=request_role))
    return ModelCommand(request=decision.model_request, claims=claims)  # type: ignore[arg-type]


def _apply_tool_request(
    kernel: DecisionRuntime,
    agent: AgentInstance,
    decision: AgentDecision,
    profile: AgentProfile,
    claims: tuple[Any, ...],
) -> ToolCommand:
    assert decision.tool_request is not None
    tool = decision.tool_request
    if not _capability_allowed(tool.capability, profile.capabilities):
        raise PermissionError(_Msg.AGENT_TOOL_DENIED.format(agent_id=agent.agent_id, capability=tool.capability))
    descriptor = kernel.capability_catalog.by_id.get(tool.capability)
    if descriptor is None:
        raise ValueError(_Msg.UNKNOWN_TOOL.format(capability=tool.capability))
    try:
        validate(tool.parameters, descriptor.parameters_schema)
    except ValidationError as error:
        raise ValueError(_Msg.TOOL_PARAMS_MISMATCH.format(capability=tool.capability, message=error.message)) from error
    task = kernel.store.get_task(agent.task_id)
    assert task is not None
    return ToolCommand(
        request={
            "capability": tool.capability,
            "parameters": tool.parameters,
            "complete_task": tool.complete_task,
            "tool_call_id": tool.tool_call_id,
            "continuation": tool.continuation,
            "session_id": task.session_id,
        },
        claims=claims,
    )


def _apply_delegations(
    kernel: DecisionRuntime,
    _agent: AgentInstance,
    decision: AgentDecision,
    profile: AgentProfile,
    claims: tuple[Any, ...],
) -> DelegateCommand:
    if not profile.can_delegate:
        raise PermissionError(_Msg.PROFILE_CANNOT_DELEGATE.format(profile_id=profile.id))
    delegation_requests: list[dict[str, str]] = []
    for delegation in decision.delegations:
        child_profile = delegation.profile_id or kernel.limits.worker_profile
        if child_profile not in profile.child_profiles or child_profile not in kernel._profiles:
            raise PermissionError(_Msg.PROFILE_CANNOT_CREATE.format(profile_id=profile.id, child_profile=child_profile))
        delegation_requests.append({"instruction": delegation.instruction, "profile_id": child_profile})
    return DelegateCommand(requests=tuple(delegation_requests), claims=claims)


def _apply_completion(decision: AgentDecision, claims: tuple[Any, ...]) -> CompleteCommand:
    return CompleteCommand(
        summary=decision.completion.summary,  # type: ignore[union-attr]
        artifacts=decision.completion.artifacts,  # type: ignore[union-attr]
        silent=decision.completion.silent,  # type: ignore[union-attr]
        claims=claims,
    )


def _apply_wait(kernel: DecisionRuntime, agent: AgentInstance, claims: tuple[Any, ...]) -> WaitCommand:
    active_child = any(not child.terminal for child in kernel.store.children(agent.agent_id))
    if not active_child and not kernel.store.has_pending_child_reports(agent.agent_id):
        raise ValueError(_Msg.WAIT_WITHOUT_CHILDREN)
    return WaitCommand(claims=claims)


def _apply_failure(decision: AgentDecision, claims: tuple[Any, ...]) -> FailCommand:
    return FailCommand(summary=decision.failure, error=decision.failure, claims=claims)  # type: ignore[arg-type]


# -- AMP 摄入 ------------------------------------------------------------


class IngressRuntime(Protocol):
    configuration: EngineConfiguration
    store: SQLiteRuntimeStore
    _inbox: Path
    _archive: Path
    _profiles: dict[str, AgentProfile]
    _amp_queue: list[Any]

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...


def ingest_ready(kernel: IngressRuntime) -> tuple[str, ...]:
    ingested: list[str] = []
    while kernel._amp_queue:
        amp = kernel._amp_queue.pop(0)
        try:
            _ingest_amp(kernel, amp, ingested)
        except (ValueError, TypeError) as error:
            logger.warning("AMP ingress rejected in-memory reason=%s", error)
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
    data = amp.payload.data
    if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
        raise ValueError(_Msg.RESERVED_TOOL_EVENT)
    if data.get("ambient") is True:
        situation_id = kernel.store.add_situation(
            amp.header.source["app"],
            amp.payload.type,
            amp.payload.summary,
            amp.to_dict(),
            10 if amp.payload.type == "system.tick" else 100,
            kernel.limits.ambient_ttl_seconds,
        )
        ingested.append(situation_id)
        return
    autonomous = amp.payload.type == "system.tick"
    budget = kernel.configuration.autonomous_budget if autonomous else kernel.configuration.interactive_budget
    task = kernel.store.create_task(
        external_message_id=amp.header.message_id,
        session_id=amp.payload.session_id,
        summary=amp.payload.summary,
        payload={"amp": amp.to_dict()},
        autonomous=autonomous,
        root_profile=kernel.limits.root_profile,
        budget=budget,
        priority=10 if autonomous else 100,
    )
    if task is not None:
        ingested.append(task.task_id)


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
        if self._capability_catalog is not None:
            raise RuntimeError(_Msg.CATALOG_ALREADY_INSTALLED)
        self._capability_catalog = catalog

    async def submit_amp(self, amp: AmpEnvelope) -> None:
        async with self._lock:
            self._amp_queue.append(amp)

    def _ingest_ready(self) -> tuple[str, ...]:
        return ingest_ready(self)

    def brain_context(self) -> BrainContextSnapshot:
        return build_brain_context(self.store)

    def recall_memory(self, query: str) -> MemoryContextSnapshot:
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
            entries.append(MemoryEntry(task.task_id, task.root_summary, agent.last_summary or None, task.updated_at))
        return tuple(entries)

    async def pump(self, max_turns: int | None = None) -> PumpResult:
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
        async with self._lock:
            ingested = await self._store_call(self._ingest_ready)
            await self._store_call(self.store.expire_tasks)
            await self._store_call(self.store.expire_situations)
            claims = await self._store_call(self._claim_messages, limit)
            return ingested, claims

    async def _execute_claims(self, claims: tuple[Any, ...]) -> tuple[Any, ...]:
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
        processed: list[str] = []
        failed: list[str] = []
        for claim, result in zip(claims, decisions, strict=True):
            message, agent, _task = claim
            try:
                if isinstance(result, BaseException):
                    raise result  # noqa: TRY301
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
            bool(self._amp_queue)
            or any(self._inbox.glob("*.json"))
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
        return build_task_detail(self.store, task_id)

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        return build_agent_detail(self.store, agent_id)

    def status(self) -> dict[str, Any]:
        return {**self.store.counts(), "brain_context_generated_at": self.brain_context().generated_at}

    async def cancel_task(self, task_id: str, reason: str) -> None:
        await self._store_call(self.store.cancel_task, task_id, reason)
        await self._blocking_call(self._archive_terminal_tasks)

    async def cancel_autonomous_tasks(self, reason: str) -> tuple[str, ...]:
        cancelled = []
        for task in self.store.tasks(active_only=True):
            if task.autonomous:
                await self._store_call(self.store.cancel_task, task.task_id, reason)
                cancelled.append(task.task_id)
        await self._blocking_call(self._archive_terminal_tasks)
        return tuple(cancelled)

    def _archive_terminal_tasks(self) -> None:
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
        self.shutdown()
        shutil.rmtree(self._workspace)

    def shutdown(self) -> None:
        self._amp_queue.clear()
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
        self._wake = asyncio.Event()

    def bind_tool_executors(self, bindings: tuple[ToolExecutorBinding, ...]) -> None:
        catalog = self._tools.bind(bindings)
        self._state.install_capability_catalog(CapabilityCatalogSnapshot(catalog.capabilities))

    async def submit_amp(self, value: object) -> str:
        amp = AmpEnvelope.parse(value)
        if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
            raise ValueError(_Msg.RESERVED_EVENT_TYPE.format(amp_type=amp.payload.type))
        if amp.payload.type != "system.tick":
            cancelled = set(await self._state.cancel_autonomous_tasks("external_activity"))
            for task, task_id in tuple(self._model_activity_tasks.items()):
                if task_id in cancelled:
                    task.cancel()
        await self._state.submit_amp(amp)
        self._wake.set()
        return amp.header.message_id

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        async with self._pump_lock:
            recoveries = await self._tools.recover_pending()
            result: PumpResult = await self._state.pump(max_turns)
            receipts = await self._tools.execute_pending()
            self._ensure_model_dispatcher()
            if self._memory_store is not None:
                for entry in self._state.completed_memory_entries():
                    try:
                        await asyncio.to_thread(self._memory_store.remember, entry)
                    except Exception as error:
                        logger.warning(
                            "Memory remember failed task_id=%s error_type=%s",
                            entry.task_id,
                            type(error).__name__,
                        )
            response = asdict(result)
            response["tool_recovery_receipts_emitted"] = recoveries
            response["tool_receipts_emitted"] = receipts
            return response

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            if self._state.has_work():
                await self.pump()
                continue
            if self._state.has_pending_model_requests():
                self._ensure_model_dispatcher()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._idle_wait_seconds)

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
            await self._state.complete_model(activity, None, "cancelled:external_activity")
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
            pending = tuple(self._model_activity_tasks)
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

    def brain_context(self) -> dict[str, Any]:
        return self._state.brain_context().to_dict()
