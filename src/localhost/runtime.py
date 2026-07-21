"""Localhost application runtime for the RFC 0012 homogeneous-Agent loop."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.ai.vnext import ModelGatewayService
from src.contracts.agent import (
    AgentHandler,
    AgentLimits,
    AgentProfile,
    CapabilityCatalogSnapshot,
    KernelConfiguration,
    TaskBudget,
)
from src.contracts.amp import AmpEnvelope, new_amp
from src.contracts.configuration import AuroraConfig, load_configuration
from src.contracts.model import ModelRequest
from src.kernel.runtime import AgentKernel, PumpResult
from src.localhost.autonomy import AutonomyQuota
from src.localhost.router import CommandRouter
from src.localhost.tool_dispatcher import ToolDispatcher
from src.memory.service import MemoryService
from src.prompt import PromptComposer, load_prompt_catalog
from src.utils.log_utils import get_logger

logger = get_logger("aurora.runtime")

if TYPE_CHECKING:
    from src.localhost.command_types import CommandResult, RuntimeInput
    from src.localhost.ports import ToolExecutorBinding


def _load_handler(specification: str, composer: PromptComposer, memory_service: Any = None) -> AgentHandler:
    module_name, separator, attribute = specification.partition(":")
    if not separator:
        raise ValueError(f"Agent implementation must use module:attribute syntax: {specification}")
    implementation = getattr(importlib.import_module(module_name), attribute)
    handler = implementation()
    installer = getattr(handler, "install_prompt_composer", None)
    if callable(installer):
        installer(composer)
    mem_installer = getattr(handler, "install_memory_service", None)
    if callable(mem_installer):
        mem_installer(memory_service)
    if not callable(getattr(handler, "handle", None)):
        raise TypeError(f"Agent implementation does not provide handle(): {specification}")
    return handler


@dataclass(slots=True)
class AuroraRuntime:
    configuration: AuroraConfig
    kernel: AgentKernel
    model_gateway: ModelGatewayService
    _pump_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _shutdown_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _model_dispatch_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _model_activity_tasks: dict[asyncio.Task[None], str] = field(default_factory=dict, init=False, repr=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _autonomy_quota: AutonomyQuota = field(init=False, repr=False)
    _command_router: CommandRouter = field(init=False, repr=False)
    _tool_dispatcher: ToolDispatcher = field(init=False, repr=False)
    _stop_requester: Callable[[], None] | None = field(default=None, init=False, repr=False)

    @classmethod
    def create(
        cls,
        root: Path,
        profile: str | None = None,
        *,
        configuration: AuroraConfig | None = None,
        tool_bindings: tuple[ToolExecutorBinding, ...] | None = (),
    ) -> "AuroraRuntime":
        configuration = configuration or load_configuration(root, profile)
        profiles = tuple(
            AgentProfile(
                id=item.id,
                implementation=item.implementation,
                model_role=item.model_role,
                capabilities=item.capabilities,
                can_delegate=item.can_delegate,
                child_profiles=item.child_profiles,
            )
            for item in configuration.agents
        )
        runtime_agents = configuration.runtime.agents
        limits = AgentLimits(
            root_profile=runtime_agents.root_profile,
            worker_profile=runtime_agents.worker_profile,
            memory_agent_profile=runtime_agents.memory_agent_profile,
            max_active_agents=runtime_agents.max_active_agents,
            max_agents_per_task=runtime_agents.max_agents_per_task,
            max_depth=runtime_agents.max_depth,
            max_children_per_agent=runtime_agents.max_children_per_agent,
            turn_concurrency=runtime_agents.turn_concurrency,
            model_concurrency=runtime_agents.model_concurrency,
            tool_concurrency=runtime_agents.tool_concurrency,
            blocking_workers=runtime_agents.blocking_workers,
            lease_seconds=runtime_agents.lease_seconds,
            ambient_ttl_seconds=runtime_agents.ambient_ttl_seconds,
        )
        kernel_config = KernelConfiguration(
            workspace=str(configuration.runtime.workspace),
            profiles=profiles,
            limits=limits,
            interactive_budget=TaskBudget(
                configuration.runtime.interactive_budget.max_model_calls,
                configuration.runtime.interactive_budget.max_tool_calls,
                configuration.runtime.interactive_budget.max_duration_seconds,
            ),
            autonomous_budget=TaskBudget(
                configuration.runtime.autonomous_budget.max_model_calls,
                configuration.runtime.autonomous_budget.max_tool_calls,
                configuration.runtime.autonomous_budget.max_duration_seconds,
            ),
        )
        catalog = load_prompt_catalog(configuration.root, frozenset(profile.id for profile in profiles))
        memory_service = MemoryService(configuration, configuration.root / "data", configuration.runtime.workspace)
        composer = PromptComposer(catalog, memory=memory_service)
        handlers = {profile.id: _load_handler(profile.implementation, composer, memory_service) for profile in profiles}
        kernel = AgentKernel(kernel_config, handlers)
        runtime = cls(
            configuration,
            kernel,
            ModelGatewayService(configuration),
        )
        runtime._command_router = CommandRouter(runtime)
        runtime._tool_dispatcher = ToolDispatcher(kernel, kernel)
        runtime._autonomy_quota = AutonomyQuota(
            configuration.runtime.workspace / "process" / "autonomy-quota.json",
            configuration.runtime.autonomy,
        )
        if tool_bindings is not None:
            runtime.bind_tool_executors(tool_bindings)
        return runtime

    async def submit_amp(self, value: object) -> str:
        amp = AmpEnvelope.parse(value)
        if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
            raise ValueError(f"reserved internal event type: {amp.payload.type}")
        if amp.payload.type != "system.tick":
            cancelled = set(await self.kernel.cancel_autonomous_tasks("external_activity"))
            for task, task_id in tuple(self._model_activity_tasks.items()):
                if task_id in cancelled:
                    task.cancel()
        await self.kernel.submit_amp(amp)
        self._wake.set()
        return amp.header.message_id

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str:
        """Normalize one transport message into the shared AMP ingress."""
        data = dict(request.data)
        data["text"] = text
        if request.actor_id is not None:
            data["actor_id"] = request.actor_id
        amp = new_amp(
            event_type="message.received",
            session_id=request.session_id,
            summary=text,
            data=data,
            source_app=request.source_app,
            source_instance=request.source_instance,
        ).to_dict()
        if request.idempotency_key is not None:
            amp["header"]["message_id"] = str(
                uuid5(
                    NAMESPACE_URL,
                    f"aurora-runtime-input:{request.origin}:{request.source_instance}:{request.idempotency_key}",
                )
            )
        return await self.submit_amp(amp)

    async def route_input(self, request: RuntimeInput) -> CommandResult:
        return await self._command_router.route(request)

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        self._stop_requester = requester

    def bind_tool_executors(self, bindings: tuple[ToolExecutorBinding, ...]) -> None:
        catalog = self._tool_dispatcher.bind(bindings)
        self.kernel.install_capability_catalog(CapabilityCatalogSnapshot(catalog.capabilities))

    def request_shutdown(self) -> None:
        if self._stop_requester is not None:
            self._stop_requester()

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        async with self._pump_lock:
            recoveries_emitted = await self._tool_dispatcher.recover_processing_tools()
            result: PumpResult = await self.kernel.pump(max_turns)
            receipts_emitted = await self._tool_dispatcher.dispatch_pending_tools()
            response = result.to_dict()
            response["tool_recovery_receipts_emitted"] = recoveries_emitted
            response["tool_receipts_emitted"] = receipts_emitted
            self._ensure_model_dispatcher()
            return response

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            if self.kernel.has_work():
                await self.pump()
                continue
            if self.kernel.has_pending_model_requests():
                self._ensure_model_dispatcher()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=self.configuration.runtime.autonomy.scan_seconds,
                )

    def _ensure_model_dispatcher(self) -> None:
        if self._model_dispatch_task is None or self._model_dispatch_task.done():
            self._model_dispatch_task = asyncio.create_task(self._dispatch_models(), name="aurora-model-activities")

    async def _dispatch_models(self) -> None:
        while True:
            activities = await self.kernel.claim_model_requests(self.kernel.limits.model_concurrency)
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
        task = self.kernel.get_task(activity.task_id)
        if task is None or task.terminal:
            return
        if task.autonomous and not self._autonomy_quota.reserve_model_call():
            await self.kernel.complete_model(activity, None, "autonomous_daily_budget")
            await self.kernel.cancel_task(task.task_id, "autonomous_daily_budget")
            return
        try:
            result = await self.model_gateway.complete(ModelRequest.from_dict(activity.request))
        except asyncio.CancelledError:
            await self.kernel.complete_model(activity, None, "cancelled:external_activity")
            raise
        except Exception as error:
            await self.kernel.complete_model(activity, None, f"{type(error).__name__}: {error}")
            return
        await self.kernel.complete_model(activity, result.to_dict(), None)
        if task.autonomous:
            self._autonomy_quota.record_tokens(result.usage.prompt_tokens + result.usage.completion_tokens)

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
            if self._model_dispatch_task is not None:
                self._model_dispatch_task.cancel()
            for task in tuple(self._model_activity_tasks):
                task.cancel()
            await asyncio.gather(
                *(
                    tuple(self._model_activity_tasks)
                    + ((self._model_dispatch_task,) if self._model_dispatch_task else ())
                ),
                return_exceptions=True,
            )
            self.kernel.shutdown()

    def status(self) -> dict[str, Any]:
        return {
            **self.kernel.status(),
            "autonomy_quota": self._autonomy_quota.status(),
            "model_dispatch_active": self._model_dispatch_task is not None and not self._model_dispatch_task.done(),
            "active_model_activities": len(self._model_activity_tasks),
        }

    def task(self, task_id: str) -> dict[str, Any] | None:
        return self.kernel.task_detail(task_id)

    def agent(self, agent_id: str) -> dict[str, Any] | None:
        return self.kernel.agent_detail(agent_id)

    def brain_context(self) -> dict[str, Any]:
        return self.kernel.brain_context().to_dict()
