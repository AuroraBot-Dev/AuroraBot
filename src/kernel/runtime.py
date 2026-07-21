"""RFC 0012 durable homogeneous-Agent scheduler and causal boundary."""

from __future__ import annotations

import asyncio
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from jsonschema import ValidationError, validate

from src.contracts.agent import (
    ActivityRequest,
    AgentContext,
    AgentDecision,
    AgentHandler,
    AgentInstance,
    AgentLimits,
    BrainContextSnapshot,
    CapabilityCatalogSnapshot,
    KernelConfiguration,
    TaskState,
    ToolLease,
)
from src.contracts.amp import AmpEnvelope
from src.kernel.brain import build_brain_context
from src.kernel.debug import agent_detail as build_agent_detail
from src.kernel.debug import reject_active_legacy_workspace
from src.kernel.debug import task_detail as build_task_detail
from src.kernel.runtime_ingress import ingest_ready as ingest_runtime_ready
from src.kernel.store import SQLiteRuntimeStore
from src.utils.log_utils import get_logger
from src.utils.serialization import atomic_write_json

logger = get_logger("aurora.kernel")
_INVALID_TOOL_OUTCOME = "invalid Tool outcome"


def _capability_allowed(capability: str, policies: frozenset[str]) -> bool:
    return (
        "*" in policies
        or capability in policies
        or any(policy.endswith(".*") and capability.startswith(policy[:-1]) for policy in policies)
    )


@dataclass(frozen=True, slots=True)
class PumpResult:
    ingested_task_ids: tuple[str, ...]
    processed_message_ids: tuple[str, ...]
    failed_message_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentKernel:
    """Owns durable Task/Agent state while delegating all cognition and external I/O."""

    def __init__(
        self,
        configuration: KernelConfiguration,
        handlers: dict[str, AgentHandler],
    ) -> None:
        self.configuration = configuration
        self._profiles = {profile.id: profile for profile in configuration.profiles}
        if set(self._profiles) != set(handlers):
            raise ValueError("Agent handlers must exactly match configured profiles")
        if configuration.limits.root_profile not in self._profiles:
            raise ValueError("root Agent profile is not configured")
        self._handlers = handlers
        self._workspace = Path(configuration.workspace)
        self._inbox = self._workspace / "inbox"
        self._process = self._workspace / "process"
        self._archive = self._workspace / "archive"
        self._task_archive = self._archive / "tasks"
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
        self._capability_catalog: CapabilityCatalogSnapshot | None = None
        self._lock = asyncio.Lock()
        logger.info(
            "Agent Kernel initialized workspace=%s profiles=%d active_tasks=%d",
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
            raise RuntimeError("capability catalog is already installed")
        self._capability_catalog = catalog

    async def submit_amp(self, amp: AmpEnvelope) -> None:
        async with self._lock:
            await self._blocking_call(
                atomic_write_json,
                self._inbox / f"{amp.header.message_id}.json",
                amp.to_dict(),
            )

    def ingest_ready(self) -> tuple[str, ...]:
        return ingest_runtime_ready(self)

    def brain_context(self) -> BrainContextSnapshot:
        return build_brain_context(self.store)

    async def pump(self, max_turns: int | None = None) -> PumpResult:
        """Ingest ready AMP files and process a bounded set of independent Agent turns."""
        limit = max_turns or self.limits.turn_concurrency
        if limit <= 0:
            raise ValueError("max_turns must be positive")
        async with self._lock:
            ingested = await self._store_call(self.ingest_ready)
            await self._store_call(self.store.expire_tasks)
            await self._store_call(self.store.expire_situations)
            claims = await self._store_call(self._claim_messages, limit)
        if not claims:
            await self._blocking_call(self._archive_terminal_tasks)
            return PumpResult(ingested, (), ())
        loop = asyncio.get_running_loop()
        decisions = await asyncio.gather(
            *(loop.run_in_executor(self._turn_executor, self._handle_claim, claim) for claim in claims),
            return_exceptions=True,
        )
        processed: list[str] = []
        failed: list[str] = []
        for claim, result in zip(claims, decisions, strict=True):
            message, agent, _task = claim
            try:
                if isinstance(result, BaseException):
                    raise result
                await self._store_call(self._apply_authorized_decision, message, agent, result)
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
                    await self._store_call(self._apply_failure, message, agent, f"{type(error).__name__}: {error}")
                except Exception:
                    await self._store_call(self.store.fail_message, message.message_id, agent.agent_id, str(error))
                failed.append(message.message_id)
        await self._blocking_call(self._archive_terminal_tasks)
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

    def _handle_claim(self, claim: tuple[Any, AgentInstance, TaskState]) -> AgentDecision:
        message, agent, task = claim
        profile = self._profiles[agent.profile_id]
        descriptors = tuple(
            descriptor
            for descriptor in self.capability_catalog.capabilities
            if _capability_allowed(descriptor.id, profile.capabilities)
        )
        context = AgentContext(
            task=task,
            agent=agent,
            message=message,
            children=self.store.children(agent.agent_id),
            profile=profile,
            capabilities=descriptors,
            brain=self.brain_context(),
            memory_agent_profile=self.limits.memory_agent_profile,
        )
        return self._handlers[agent.profile_id].handle(context)

    def _apply_failure(self, message: Any, agent: AgentInstance, error: str) -> None:
        action = {"kind": "fail", "summary": error, "error": error, "claims": []}
        self.store.apply_decision(
            message=message,
            agent=agent,
            action=action,
            state_patch={},
            limits=self._limit_dict(),
            priority=message.priority,
        )

    def _apply_authorized_decision(self, message: Any, agent: AgentInstance, decision: AgentDecision) -> None:
        profile = self._profiles[agent.profile_id]
        action: dict[str, Any]
        if decision.model_request is not None:
            request_role = decision.model_request.get("role")
            if request_role != profile.model_role:
                raise PermissionError(f"Agent {agent.agent_id} cannot request model role {request_role}")
            action = {"kind": "model", "request": decision.model_request, "summary": "model.requested"}
        elif decision.tool_request is not None:
            tool = decision.tool_request
            if not _capability_allowed(tool.capability, profile.capabilities):
                raise PermissionError(f"Agent {agent.agent_id} cannot request {tool.capability}")
            descriptor = self.capability_catalog.by_id.get(tool.capability)
            if descriptor is None:
                raise ValueError(f"unknown Tool capability {tool.capability}")
            try:
                validate(tool.parameters, descriptor.parameters_schema)
            except ValidationError as error:
                raise ValueError(f"Tool parameters do not match {tool.capability}: {error.message}") from error
            task = self.store.get_task(agent.task_id)
            assert task is not None
            action = {
                "kind": "tool",
                "summary": f"tool.requested:{tool.capability}",
                "request": {
                    "capability": tool.capability,
                    "parameters": tool.parameters,
                    "complete_task": tool.complete_task,
                    "tool_call_id": tool.tool_call_id,
                    "continuation": tool.continuation,
                    "session_id": task.session_id,
                },
            }
        elif decision.delegations:
            if not profile.can_delegate:
                raise PermissionError(f"Agent profile {profile.id} cannot delegate")
            requests = []
            for delegation in decision.delegations:
                child_profile = delegation.profile_id or self.limits.worker_profile
                if child_profile not in profile.child_profiles or child_profile not in self._profiles:
                    raise PermissionError(f"Agent profile {profile.id} cannot create {child_profile}")
                requests.append({"instruction": delegation.instruction, "profile_id": child_profile})
            action = {"kind": "delegate", "requests": requests, "summary": f"delegated {len(requests)} child Agent(s)"}
        elif decision.completion is not None:
            action = {
                "kind": "complete",
                "summary": decision.completion.summary,
                "artifacts": list(decision.completion.artifacts),
                "silent": decision.completion.silent,
            }
        elif decision.wait_for_children:
            active_child = any(not child.terminal for child in self.store.children(agent.agent_id))
            if not active_child and not self.store.has_pending_child_reports(agent.agent_id):
                raise ValueError("Agent cannot wait without active children")
            action = {"kind": "wait", "summary": "waiting for child Agents"}
        elif decision.failure is not None:
            action = {"kind": "fail", "summary": decision.failure, "error": decision.failure}
        else:
            raise ValueError("unsupported Agent decision")
        action["claims"] = list(decision.claims)
        self.store.apply_decision(
            message=message,
            agent=agent,
            action=action,
            state_patch=decision.state_patch,
            limits=self._limit_dict(),
            priority=message.priority,
        )

    def _limit_dict(self) -> dict[str, int]:
        return {
            "max_active_agents": self.limits.max_active_agents,
            "max_agents_per_task": self.limits.max_agents_per_task,
            "max_depth": self.limits.max_depth,
            "max_children_per_agent": self.limits.max_children_per_agent,
        }

    def has_work(self) -> bool:
        counts = self.store.counts()
        return (
            any(self._inbox.glob("*.json"))
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
        status: str,
        summary: str,
        result: dict[str, Any] | None,
        error: str | None,
        source_app: str,
        source_instance: str,
    ) -> None:
        if status not in {"succeeded", "failed", "unknown"}:
            raise ValueError(_INVALID_TOOL_OUTCOME)
        if (status == "succeeded" and error is not None) or (
            status != "succeeded" and (not error or result is not None)
        ):
            raise ValueError(_INVALID_TOOL_OUTCOME)
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
            raise ValueError(f"Tool completion does not match an active request: {request_id}")

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
        self._turn_executor.shutdown(wait=True, cancel_futures=True)
        self._blocking_executor.shutdown(wait=True, cancel_futures=True)
        self._store_executor.shutdown(wait=True, cancel_futures=True)
