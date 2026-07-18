"""Composition root for the RFC 0012 durable homogeneous-Agent runtime."""

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
    CapabilityDescriptor,
    KernelConfiguration,
    TaskBudget,
)
from src.contracts.amp import AmpEnvelope, new_amp
from src.contracts.configuration import AuroraConfig, load_configuration
from src.contracts.model import ModelRequest
from src.kernel.runtime import AgentKernel, PumpResult
from src.localhost.chat import ChatService
from src.localhost.router import CommandRouter
from src.localhost.scheduler import CognitiveScheduler
from src.platform.console import ConsolePlatform
from src.platform.dashboard import DashboardPlatform
from src.platform.mcp import MCPPlatform
from src.utils.log_utils import configure_logging, get_logger

logger = get_logger("aurora.runtime")

if TYPE_CHECKING:
    from src.localhost.command_types import CommandResult, RuntimeInput


def _load_handler(specification: str) -> AgentHandler:
    module_name, separator, attribute = specification.partition(":")
    if not separator:
        raise ValueError(f"Agent implementation must use module:attribute syntax: {specification}")
    implementation = getattr(importlib.import_module(module_name), attribute)
    handler = implementation()
    if not callable(getattr(handler, "handle", None)):
        raise TypeError(f"Agent implementation does not provide handle(): {specification}")
    return handler


@dataclass(slots=True)
class AuroraRuntime:
    configuration: AuroraConfig
    kernel: AgentKernel
    model_gateway: ModelGatewayService
    console_platform: ConsolePlatform
    mcp_platform: MCPPlatform
    dashboard_platform: DashboardPlatform
    chat: ChatService
    _pump_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _start_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _shutdown_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _console_messages: list[str] = field(default_factory=list, init=False, repr=False)
    _console_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue, init=False, repr=False)
    _model_dispatch_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _model_activity_tasks: dict[asyncio.Task[None], str] = field(default_factory=dict, init=False, repr=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _scheduler: CognitiveScheduler | None = field(default=None, init=False, repr=False)
    _command_router: CommandRouter = field(init=False, repr=False)
    _stop_requester: Callable[[], None] | None = field(default=None, init=False, repr=False)

    @classmethod
    def create(cls, root: Path, profile: str | None = None) -> "AuroraRuntime":
        configuration = load_configuration(root, profile)
        configure_logging(configuration.logging_level, configuration.root / "logs" / "aurora.log")
        profiles = tuple(
            AgentProfile(
                id=item.id,
                implementation=item.implementation,
                model_role=item.model_role,
                prompt=item.prompt,
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
            effect_concurrency=runtime_agents.effect_concurrency,
            blocking_workers=runtime_agents.blocking_workers,
            lease_seconds=runtime_agents.lease_seconds,
            ambient_ttl_seconds=runtime_agents.ambient_ttl_seconds,
        )
        kernel_config = KernelConfiguration(
            workspace=str(configuration.runtime.workspace),
            soul_content=configuration.soul_path.read_text(encoding="utf-8"),
            soul_hash=configuration.soul_hash,
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
        handlers = {profile.id: _load_handler(profile.implementation) for profile in profiles}
        kernel = AgentKernel(kernel_config, handlers)
        configured_catalog = CapabilityCatalogSnapshot(
            tuple(
                CapabilityDescriptor(item.id, item.description, item.parameters_schema, item.result_mode)
                for adapter in configuration.adapters
                for item in adapter.capabilities
            )
        )
        kernel.install_capability_catalog(configured_catalog)
        console_capabilities = frozenset(
            capability.id
            for adapter in configuration.adapters
            if adapter.implementation == "src.platform.console:ConsolePlatform"
            for capability in adapter.capabilities
        )
        chat = ChatService(configuration.dashboard)
        runtime = cls(
            configuration,
            kernel,
            ModelGatewayService(configuration),
            ConsolePlatform(console_capabilities),
            MCPPlatform(configuration),
            DashboardPlatform(chat.deliver_bot_reply),
            chat,
        )
        runtime._command_router = CommandRouter(runtime)
        chat.bind_input_dispatcher(runtime.route_input)
        runtime.mcp_platform.set_tool_result_observer(runtime._observe_mcp_result)
        runtime._scheduler = CognitiveScheduler(
            configuration.runtime.workspace / "process" / "scheduler-state.json",
            configuration.runtime.scheduler,
        )
        return runtime

    async def _ensure_started(self) -> None:
        if self._started:
            return
        # Dashboard, console and run_forever may all enter startup concurrently.
        # Serialize the side effects so SQLite initialization and MCP launch happen once.
        async with self._start_lock:
            if self._started:
                return
            await self.chat.start()
            await self.mcp_platform.start(self.kernel)
            self._started = True

    async def start(self) -> None:
        await self._ensure_started()

    async def submit_amp(self, value: object) -> str:
        await self._ensure_started()
        amp = AmpEnvelope.parse(value)
        if amp.payload.type not in {"system.tick", "effect.succeeded", "effect.failed"}:
            cancelled = set(await self.kernel.cancel_autonomous_tasks("external_activity"))
            for task, task_id in tuple(self._model_activity_tasks.items()):
                if task_id in cancelled:
                    task.cancel()
            if self._scheduler is not None:
                self._scheduler.on_external_activity()
        await self.kernel.submit_amp(amp)
        self._wake.set()
        return amp.header.message_id

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str:
        """Normalize one transport message into the shared AMP ingress."""
        data = dict(request.data)
        data.update({"text": text, "reply_capability": request.reply_capability})
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
        await self._ensure_started()
        return await self._command_router.route(request)

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        self._stop_requester = requester

    def request_shutdown(self) -> None:
        if self._stop_requester is not None:
            self._stop_requester()

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        async with self._pump_lock:
            await self._ensure_started()
            result: PumpResult = await self.kernel.pump(max_turns)
            local_result, dashboard_result, mcp_result = await asyncio.gather(
                self.console_platform.execute_pending_effects(self.kernel),
                self.dashboard_platform.execute_pending_effects(self.kernel),
                self.mcp_platform.execute_pending_effects(self.kernel),
            )
            response = result.to_dict()
            response["platform_receipts_emitted"] = (
                local_result.receipts_emitted + dashboard_result.receipts_emitted + mcp_result.receipts_emitted
            )
            self._ensure_model_dispatcher()
            if self._scheduler is not None:
                self._scheduler.reconcile(self.kernel.tasks())
            return response

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        await self._ensure_started()
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            if self._scheduler is not None:
                self._scheduler.reconcile(self.kernel.tasks())
                if self._scheduler.can_tick(self.kernel.tasks()):
                    tick = new_amp(
                        event_type="system.tick",
                        session_id="kernel:autonomy",
                        summary="Autonomous cognitive tick",
                        data={"interval_seconds": self._scheduler.state.current_interval_seconds},
                        source_app="kernel.scheduler",
                        source_instance="localhost",
                    )
                    await self.kernel.submit_amp(tick)
                    self._scheduler.mark_tick_emitted()
            if self.kernel.has_work():
                await self.pump()
                continue
            if self.kernel.has_pending_model_requests():
                self._ensure_model_dispatcher()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=self.configuration.runtime.scheduler.scan_seconds,
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
        if task.autonomous and self._scheduler is not None and not self._scheduler.reserve_autonomous_model_call():
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
        if task.autonomous and self._scheduler is not None:
            self._scheduler.record_autonomous_tokens(result.usage.prompt_tokens + result.usage.completion_tokens)

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
            await self.mcp_platform.shutdown()
            self.kernel.shutdown()

    def drain_console_messages(self) -> tuple[str, ...]:
        messages = tuple(self._console_messages)
        self._console_messages.clear()
        while not self._console_queue.empty():
            self._console_queue.get_nowait()
        return messages

    async def next_console_message(self) -> str:
        message = await self._console_queue.get()
        if message in self._console_messages:
            self._console_messages.remove(message)
        return message

    def _observe_mcp_result(self, capability: str, result: dict[str, object]) -> None:
        if capability != "org.aurora.console.send_message" or result.get("ok") is not True:
            return
        text = result.get("text")
        if isinstance(text, str) and text:
            self._console_messages.append(text)
            self._console_queue.put_nowait(text)

    def status(self) -> dict[str, Any]:
        return {
            **self.kernel.status(),
            "scheduler": self._scheduler.status() if self._scheduler is not None else None,
            "model_dispatch_active": self._model_dispatch_task is not None and not self._model_dispatch_task.done(),
            "active_model_activities": len(self._model_activity_tasks),
        }

    def task(self, task_id: str) -> dict[str, Any] | None:
        return self.kernel.task_detail(task_id)

    def agent(self, agent_id: str) -> dict[str, Any] | None:
        return self.kernel.agent_detail(agent_id)

    def brain_context(self) -> dict[str, Any]:
        return self.kernel.brain_context().to_dict()
