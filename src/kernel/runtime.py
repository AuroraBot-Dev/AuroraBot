# ruff: noqa: TC001, TRY003, SIM105
"""Async cognitive event runtime with real capability injection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from src.config import Config
from src.kernel.models import CognitiveEvent, EventOutput, NodeContext, NodeResult, utcnow
from src.kernel.registry import NodeRegistry
from src.kernel.store import EventStore
from src.kernel.workspace import CognitiveWorkspace
from src.utils.log_utils import get_logger

logger = get_logger("CognitiveRuntime")


@dataclass(slots=True)
class RuntimeServices:
    gateway: Any
    mcp: Any
    memory: Any


class CognitiveRuntime:
    def __init__(
        self,
        registry: NodeRegistry,
        services: RuntimeServices,
        *,
        workspace: CognitiveWorkspace | None = None,
        store: EventStore | None = None,
        tick_interval: float | None = None,
    ) -> None:
        self.workspace = workspace or CognitiveWorkspace(Config.KERNEL_DATA_DIR)
        self.store = store or EventStore(self.workspace.root)
        self.registry = registry
        self.services = services
        self.tick_interval = tick_interval or Config.HEARTBEAT_INTERVAL
        self._nodes = {plugin.node_type: plugin.factory({}) for plugin in registry.all()}
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._tick_index = 0
        self._snapshot_cache = self._build_snapshot()

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_forever(), name="cognitive-runtime")
        await self.submit(CognitiveEvent.create("system.tick", {"kind": "bootstrap", "index": 0}, source="runtime"))

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.store.close()

    async def submit(self, event: CognitiveEvent) -> None:
        self.store.create(event)
        if event.event_type.startswith("input.") or event.event_type.startswith("effect."):
            self.workspace.write_ingress(event)
        if event.event_type in {"output.candidate", "output.published"}:
            self.workspace.write_outbox(event)
        self._snapshot_cache = self._build_snapshot()

    async def cycle(self) -> int:
        processed = 0
        for event in self.workspace.scan_external():
            await self.submit(event)
        for event in self.store.list_ready():
            if event.hop >= event.max_hops:
                if self.store.claim(event.event_id, "runtime"):
                    self.store.fail(event.event_id, "runtime", "maximum causal hop count exceeded")
                continue
            plugin = self._select_plugin(event)
            if plugin is None:
                if self.store.claim(event.event_id, "runtime"):
                    self.store.fail(event.event_id, "runtime", "no eligible cognitive node")
                continue
            if not self.store.claim(event.event_id, plugin.node_type):
                continue
            processed += 1
            try:
                result = await self._nodes[plugin.node_type].process(NodeContext(self, plugin.node_type), event)
                await self._publish_result(event, plugin.node_type, plugin.output_types, result)
            except asyncio.CancelledError:
                self.store.release(event.event_id, plugin.node_type)
                raise
            except Exception as error:
                logger.exception("node failed: %s event=%s", plugin.node_type, event.event_id)
                self.store.fail(event.event_id, plugin.node_type, f"{type(error).__name__}: {error}")
        self._snapshot_cache = self._build_snapshot()
        return processed

    async def emit(self, source: CognitiveEvent, output: EventOutput, producer: str) -> CognitiveEvent:
        child = CognitiveEvent.create(
            output.event_type,
            output.payload,
            source=producer,
            session_id=source.session_id,
            episode_id=source.episode_id,
            causation_id=source.event_id,
            tags=output.tags,
            available_at=output.available_at,
            hop=source.hop + 1,
            max_hops=source.max_hops,
        )
        await self.submit(child)
        if output.terminal:
            self.store.archive_terminal(child.event_id)
        return child

    def latest_context(self, session_id: str) -> dict[str, object]:
        frame = self.store.latest_context(session_id)
        return dict(frame.payload) if frame is not None else {"facts": [], "summary": ""}

    def snapshot(self) -> dict[str, object]:
        return dict(self._snapshot_cache)

    def _build_snapshot(self) -> dict[str, object]:
        return {
            "running": self._running,
            "states": self.store.event_state_counts(),
            "events": [
                {
                    "id": event.event_id,
                    "type": event.event_type,
                    "source": event.source,
                    "session": event.session_id,
                    "causation_id": event.causation_id,
                    "hop": event.hop,
                }
                for event in self.store.list_events()[-160:]
            ],
            "nodes": [plugin.node_type for plugin in self.registry.all()],
        }

    async def _publish_result(
        self,
        source: CognitiveEvent,
        node_id: str,
        output_types: frozenset[str],
        result: NodeResult,
    ) -> None:
        for output in result.outputs:
            if output.event_type not in output_types:
                raise ValueError(f"{node_id} emitted undeclared event type {output.event_type}")
            await self.emit(source, output, node_id)
        if result.archive_input:
            self.store.archive(source.event_id, node_id)
        else:
            self.store.release(source.event_id, node_id)

    def _select_plugin(self, event: CognitiveEvent):
        target = event.tags.get("target")
        candidates = self.registry.candidates(event)
        if isinstance(target, str):
            return next((plugin for plugin in candidates if plugin.node_type == target), None)
        return candidates[0] if len(candidates) == 1 else None

    async def _run_forever(self) -> None:
        while self._running:
            await self.cycle()
            self._tick_index += 1
            await self.submit(
                CognitiveEvent.create(
                    "system.tick",
                    {"kind": "heartbeat", "index": self._tick_index},
                    source="runtime",
                    available_at=utcnow() + timedelta(seconds=self.tick_interval),
                )
            )
            await asyncio.sleep(self.tick_interval)
