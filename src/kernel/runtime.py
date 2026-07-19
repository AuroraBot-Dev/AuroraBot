"""RFC 0012 durable homogeneous-Agent scheduler and causal boundary."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any

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
    EffectLease,
    KernelConfiguration,
    TaskState,
)
from src.contracts.amp import AmpEnvelope, AmpValidationError
from src.kernel.debug import agent_detail as build_agent_detail
from src.kernel.debug import reject_active_legacy_workspace
from src.kernel.debug import task_detail as build_task_detail
from src.kernel.store import SQLiteRuntimeStore, utc_now
from src.utils.log_utils import get_logger
from src.utils.serialization import atomic_write_json, read_json

logger = get_logger("aurora.kernel")


@dataclass(frozen=True, slots=True)
class PumpResult:
    ingested_task_ids: tuple[str, ...]
    processed_message_ids: tuple[str, ...]
    failed_message_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentKernel:
    """Owns durable Task/Agent state while delegating all cognition and external I/O."""

    def __init__(self, configuration: KernelConfiguration, handlers: dict[str, AgentHandler]) -> None:
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

    def _archive_inbox(self, source: Path, category: str) -> None:
        destination_dir = self._archive / "inbox" / category
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        if destination.exists():
            destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
        source.replace(destination)

    def ingest_ready(self) -> tuple[str, ...]:
        ingested: list[str] = []
        for path in sorted(self._inbox.glob("*.json")):
            try:
                amp = AmpEnvelope.parse(read_json(path))
            except (OSError, ValueError, TypeError, AmpValidationError) as error:
                logger.warning("AMP ingress rejected file=%s reason=%s", path.name, error)
                self._archive_inbox(path, "rejected")
                continue
            data = amp.payload.data
            if amp.payload.type in {"effect.succeeded", "effect.failed"}:
                request_id = data.get("request_id")
                matched = False
                message_id = None
                if isinstance(request_id, str):
                    matched, message_id = self.store.ingest_activity_receipt(
                        external_message_id=amp.header.message_id,
                        request_id=request_id,
                        event_type=amp.payload.type,
                        summary=amp.payload.summary,
                        payload=data,
                    )
                if not matched:
                    self.store.add_situation(
                        amp.header.source["app"],
                        amp.payload.type,
                        amp.payload.summary,
                        amp.to_dict(),
                        100,
                        self.limits.ambient_ttl_seconds,
                    )
                else:
                    ingested.append(message_id or amp.header.message_id)
                self._archive_inbox(path, "accepted")
                continue
            if data.get("ambient") is True:
                situation_id = self.store.add_situation(
                    amp.header.source["app"],
                    amp.payload.type,
                    amp.payload.summary,
                    amp.to_dict(),
                    10 if amp.payload.type == "system.tick" else 100,
                    self.limits.ambient_ttl_seconds,
                )
                ingested.append(situation_id)
                self._archive_inbox(path, "accepted")
                continue
            autonomous = amp.payload.type == "system.tick"
            budget = self.configuration.autonomous_budget if autonomous else self.configuration.interactive_budget
            task = self.store.create_task(
                external_message_id=amp.header.message_id,
                session_id=amp.payload.session_id,
                summary=amp.payload.summary,
                payload={"amp": amp.to_dict()},
                autonomous=autonomous,
                root_profile=self.limits.root_profile,
                budget=budget,
                priority=10 if autonomous else 100,
            )
            self._archive_inbox(path, "accepted" if task is not None else "duplicate")
            if task is not None:
                ingested.append(task.task_id)
        return tuple(ingested)

    def brain_context(self) -> BrainContextSnapshot:
        tasks = self.store.tasks(active_only=True)
        agents = self.store.agents(active_only=True)
        latest_activity = {}
        for task in tasks:
            events = self.store.events_for_task(task.task_id)
            latest_activity[task.task_id] = events[-1]["summary"] if events else task.root_summary
        return BrainContextSnapshot(
            persona={"content": self.configuration.soul_content, "hash": self.configuration.soul_hash},
            active_tasks=tuple(
                {
                    "task_id": task.task_id,
                    "session_id": task.session_id,
                    "summary": task.root_summary,
                    "latest_activity": latest_activity[task.task_id],
                    "status": task.status,
                    "model_calls": task.model_calls,
                    "tool_calls": task.tool_calls,
                    "updated_at": task.updated_at,
                }
                for task in tasks
            ),
            active_agents=tuple(
                {
                    "agent_id": agent.agent_id,
                    "task_id": agent.task_id,
                    "parent_agent_id": agent.parent_agent_id,
                    "profile_id": agent.profile_id,
                    "assignment": agent.assignment,
                    "status": agent.status,
                    "last_summary": agent.last_summary,
                    "updated_at": agent.updated_at,
                }
                for agent in agents
            ),
            ambient_situations=self.store.situations(),
            generated_at=utc_now(),
        )

    async def pump(self, max_turns: int | None = None) -> PumpResult:
        """Ingest ready AMP files and process a bounded set of independent Agent turns."""
        limit = max_turns or self.limits.turn_concurrency
        if limit <= 0:
            raise ValueError("max_turns must be positive")
        async with self._lock:
            await self._store_call(self.store.expire_tasks)
            await self._store_call(self.store.expire_situations)
            ingested = await self._store_call(self.ingest_ready)
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
            for capability in sorted(profile.capabilities)
            if (descriptor := self.capability_catalog.by_id.get(capability)) is not None
            and (agent.parent_agent_id is None or descriptor.result_mode != "terminal")
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
        elif decision.effect_request is not None:
            effect = decision.effect_request
            if effect.capability not in profile.capabilities:
                raise PermissionError(f"Agent {agent.agent_id} cannot request {effect.capability}")
            descriptor = self.capability_catalog.by_id.get(effect.capability)
            if descriptor is None:
                raise ValueError(f"unknown effect capability {effect.capability}")
            if agent.parent_agent_id is not None and descriptor.result_mode == "terminal":
                raise PermissionError("only the root Agent may request terminal effects")
            try:
                validate(effect.parameters, descriptor.parameters_schema)
            except ValidationError as error:
                raise ValueError(f"effect parameters do not match {effect.capability}: {error.message}") from error
            task = self.store.get_task(agent.task_id)
            assert task is not None
            action = {
                "kind": "effect",
                "summary": f"effect.requested:{effect.capability}",
                "request": {
                    "capability": effect.capability,
                    "result_mode": descriptor.result_mode,
                    "parameters": effect.parameters,
                    "tool_call_id": effect.tool_call_id,
                    "continuation": effect.continuation,
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
            any(self._inbox.glob("*.json")) or counts["pending_messages"] > 0 or counts["pending_effect_activities"] > 0
        )

    def has_pending_effect_requests(self) -> bool:
        return self.store.counts()["pending_effect_activities"] > 0

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

    async def claim_effect_requests(self) -> tuple[EffectLease, ...]:
        activities = await self._store_call(
            self.store.claim_effect_activities,
            self.limits.effect_concurrency,
            self.limits.lease_seconds,
        )
        leases = []
        for activity in activities:
            request = activity.request
            leases.append(
                EffectLease(
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
