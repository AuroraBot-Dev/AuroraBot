"""Composition root for the locally runnable minimal causal loop."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.ai.vnext import ModelGatewayService
from src.config import AuroraConfig, load_config
from src.kernel.events import AmpEnvelope, new_amp
from src.kernel.runtime import CycleResult, Kernel
from src.localhost.scheduler import CognitiveScheduler
from src.nodes.decide import DecideNode
from src.nodes.fast_gate import FastGateNode
from src.nodes.model_decide import ModelDecideNode
from src.nodes.native_agent import NativeAgentNode
from src.platform.local import LocalTestPlatform
from src.platform.mcp_platform import MCPPlatform
from src.utils.log_utils import configure_logging, get_logger

logger = get_logger("aurora.runtime")


@dataclass(slots=True)
class AuroraRuntime:
    """Coordinates the local use case without exposing Kernel to HTTP callers."""

    configuration: AuroraConfig
    kernel: Kernel
    platform: LocalTestPlatform
    mcp_platform: MCPPlatform
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _console_messages: list[str] = field(default_factory=list, init=False, repr=False)
    _console_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue, init=False, repr=False)
    _model_dispatch_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _active_model_record_id: str | None = field(default=None, init=False, repr=False)
    _wake: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _scheduler: CognitiveScheduler | None = field(default=None, init=False, repr=False)

    @classmethod
    def create(cls, root: Path, profile: str | None = None) -> "AuroraRuntime":
        configuration = load_config(root, profile)
        configure_logging(configuration.logging_level)
        nodes = {
            "builtin.decide": DecideNode(),
            "builtin.model_decide": ModelDecideNode(),
            "builtin.fast_gate": FastGateNode(),
            "builtin.native_agent": NativeAgentNode(),
        }
        enabled_nodes = {node.id: nodes[node.id] for node in configuration.nodes}
        test_capabilities = frozenset(
            capability.id
            for adapter in configuration.adapters
            if adapter.implementation == "src.platform.local:LocalTestPlatform"
            for capability in adapter.capabilities
        )
        runtime = cls(
            configuration,
            Kernel(configuration, enabled_nodes, ModelGatewayService(configuration)),
            LocalTestPlatform(test_capabilities),
            MCPPlatform(configuration),
        )
        runtime.mcp_platform.set_tool_result_observer(runtime._observe_mcp_result)
        runtime._scheduler = CognitiveScheduler(
            configuration.runtime.workspace / "process" / "scheduler-state.json",
            configuration.runtime.scheduler,
        )
        logger.info(
            "runtime created profile=%s workspace=%s nodes=%d scheduler_enabled=%s",
            configuration.runtime.profile,
            configuration.runtime.workspace,
            len(enabled_nodes),
            configuration.runtime.scheduler.enabled,
        )
        return runtime

    async def _ensure_started(self) -> None:
        if not self._started:
            logger.info("platform startup started apps=%d", len(self.configuration.apps))
            await self.mcp_platform.start(self.kernel)
            self._started = True
            logger.info(
                "platform startup completed capabilities=%d",
                len(self.kernel.capability_catalog.capabilities),
            )

    async def submit_amp(self, value: object) -> str:
        await self._ensure_started()
        amp = AmpEnvelope.parse(value)
        await self._cancel_autonomous_model_for(amp)
        if self._scheduler is not None and amp.payload.type not in {
            "system.tick",
            "effect.succeeded",
            "effect.failed",
        }:
            self._scheduler.on_external_activity()
        await self.kernel.submit_amp(amp)
        self._wake.set()
        logger.debug(
            "runtime accepted AMP message_id=%s event_type=%s session_id=%s",
            amp.header.message_id,
            amp.payload.type,
            amp.payload.session_id,
        )
        return amp.header.message_id

    async def run_cycle(self) -> dict[str, Any]:
        async with self._lock:
            await self._ensure_started()
            result: CycleResult = await self.kernel.run_cycle()
            platform_result = await self.platform.execute_pending_effects(self.kernel)
            mcp_result = await self.mcp_platform.execute_pending_effects(self.kernel)
            response = result.to_dict()
            response["platform_receipts_emitted"] = platform_result.receipts_emitted + mcp_result.receipts_emitted
            self._ensure_model_dispatcher()
            if self._scheduler is not None:
                self._scheduler.reconcile(self.kernel.episodes())
            logger.debug(
                "runtime cycle completed cycle=%d ingested=%d scheduled=%d failed=%d receipts=%d",
                result.cycle,
                len(result.ingested_record_ids),
                len(result.scheduled_record_ids),
                len(result.failed_record_ids),
                response["platform_receipts_emitted"],
            )
            return response

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """Run the time-driven cognitive loop until explicitly stopped."""
        await self._ensure_started()
        stop = stop_event or asyncio.Event()
        logger.info("runtime loop started profile=%s", self.configuration.runtime.profile)
        try:
            while not stop.is_set():
                if self._scheduler is not None:
                    self._scheduler.reconcile(self.kernel.episodes())
                    if self._scheduler.can_tick(self.kernel.episodes()):
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
                        logger.info(
                            "autonomous tick emitted message_id=%s interval_s=%.1f",
                            tick.header.message_id,
                            self._scheduler.state.current_interval_seconds,
                        )
                if self.kernel.has_cycle_work():
                    await self.run_cycle()
                    continue
                if self.kernel.has_pending_model_request():
                    self._ensure_model_dispatcher()
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=self.configuration.runtime.scheduler.scan_seconds,
                    )
        finally:
            logger.info("runtime loop stopped cycle=%d", self.kernel.cycle)

    async def shutdown(self) -> None:
        logger.info("runtime shutdown started cycle=%d", self.kernel.cycle)
        if self._model_dispatch_task is not None:
            self._model_dispatch_task.cancel()
            await asyncio.gather(self._model_dispatch_task, return_exceptions=True)
        await self.mcp_platform.shutdown()
        logger.info("runtime shutdown completed cycle=%d", self.kernel.cycle)

    def _ensure_model_dispatcher(self) -> None:
        if self._model_dispatch_task is None or self._model_dispatch_task.done():
            self._model_dispatch_task = asyncio.create_task(self._dispatch_models(), name="aurora-model-dispatcher")
            logger.debug("model dispatcher scheduled")

    async def _dispatch_models(self) -> None:
        while True:
            record = await self.kernel.claim_model_request()
            if record is None:
                logger.debug("model dispatcher idle")
                return
            self._active_model_record_id = record.record_id
            episode = self.kernel.get_episode(record.episode_id)
            if (
                episode is not None
                and episode.autonomous
                and self._scheduler is not None
                and not self._scheduler.reserve_autonomous_model_call()
            ):
                logger.warning(
                    "autonomous model quota rejected record_id=%s episode_id=%s",
                    record.record_id,
                    record.episode_id,
                )
                self.kernel.cancel_model_request(record, "autonomous_daily_budget")
                self._active_model_record_id = None
                self._wake.set()
                continue
            try:
                completed = await self.kernel.execute_model_request(record)
                if episode is not None and episode.autonomous and self._scheduler is not None:
                    completed_amp = AmpEnvelope.parse(completed.amp)
                    usage = completed_amp.payload.data.get("usage")
                    if isinstance(usage, dict):
                        tokens = int(usage.get("prompt_tokens", 0) or 0) + int(usage.get("completion_tokens", 0) or 0)
                        self._scheduler.record_autonomous_tokens(tokens)
                        logger.debug(
                            "autonomous usage recorded record_id=%s episode_id=%s tokens=%d",
                            record.record_id,
                            record.episode_id,
                            tokens,
                        )
            except asyncio.CancelledError:
                logger.warning(
                    "autonomous model dispatch interrupted record_id=%s episode_id=%s reason=external_activity",
                    record.record_id,
                    record.episode_id,
                )
                self.kernel.cancel_model_request(record, "external_activity")
                raise
            finally:
                self._active_model_record_id = None
                self._wake.set()

    async def _cancel_autonomous_model_for(self, amp: AmpEnvelope) -> None:
        if amp.payload.type in {"system.tick", "effect.succeeded", "effect.failed"}:
            return
        if (
            self._model_dispatch_task is None
            or self._model_dispatch_task.done()
            or self._active_model_record_id is None
        ):
            return
        record = self.kernel.get_record(self._active_model_record_id)
        if record is None:
            return
        episode = self.kernel.get_episode(record.episode_id)
        if episode is not None and episode.autonomous:
            logger.info(
                "external activity cancelling autonomous model message_id=%s event_type=%s record_id=%s episode_id=%s",
                amp.header.message_id,
                amp.payload.type,
                record.record_id,
                record.episode_id,
            )
            self._model_dispatch_task.cancel()

    def drain_console_messages(self) -> tuple[str, ...]:
        """Return and clear messages delivered by the console MCP application."""
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
            logger.debug("console effect observed capability=%s text_length=%d", capability, len(text))

    def record(self, record_id: str) -> dict[str, Any] | None:
        record = self.kernel.get_record(record_id)
        return record.to_dict() if record else None

    def status(self) -> dict[str, Any]:
        episodes = self.kernel.episodes()
        return {
            "cycle": self.kernel.cycle,
            "scheduler": self._scheduler.status() if self._scheduler is not None else None,
            "active_episodes": sum(not episode.terminal for episode in episodes),
            "active_autonomous_episodes": sum(episode.autonomous and not episode.terminal for episode in episodes),
            "model_dispatch_active": self._model_dispatch_task is not None and not self._model_dispatch_task.done(),
        }

    def episode(self, episode_id: str) -> dict[str, Any] | None:
        episode = self.kernel.get_episode(episode_id)
        return episode.to_dict() if episode is not None else None
