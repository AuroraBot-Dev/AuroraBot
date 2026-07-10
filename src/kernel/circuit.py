"""Cognitive topology circuit orchestrator — manages node coroutines and kernel lifecycle.

Acts as a facade over GraphRuntime, FileEventBus, HeartbeatRuntime,
and the storage layer.  Provides the same external interface as the
previous circuit for backward compatibility.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Self

from src.config import Config
from src.kernel.base import FileEvent, FileUpdate, NodeState
from src.kernel.locks import LockClient
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.kernel.base import Node
    from src.kernel.event_bus import FileEventBus
    from src.kernel.heartbeat import HeartbeatRuntime
    from src.kernel.metadata import SQLiteMetadataStore
    from src.kernel.objectstore import FileObjectStore, MemoryObjectStore

logger = get_logger("Circuit")


class Circuit:
    """Cognitive topology circuit orchestrator.

    Manages a FileEventBus and a set of Node coroutines.
    Each node runs an independent ``run()`` coroutine; file events
    flow through the bus in a directed (possibly cyclic) graph.

    Parameters
    ----------
    nodes : list[Node]
        All nodes in the circuit.
    store : SQLiteMetadataStore
        Metadata store for file state.
    objects : MemoryObjectStore | FileObjectStore
        Immutable object store for file content.
    heartbeat : HeartbeatRuntime
        Adaptive heartbeat manager.
    bus : FileEventBus
        Event bus for dispatching file events.
    """

    def __init__(
        self,
        nodes: list[Node],
        store: SQLiteMetadataStore,
        objects: MemoryObjectStore | FileObjectStore,
        heartbeat: HeartbeatRuntime,
        bus: FileEventBus,
    ) -> None:
        self._nodes = nodes
        self._store = store
        self._objects = objects
        self._heartbeat = heartbeat
        self._bus = bus
        self._node_tasks: list[asyncio.Task[None]] = []

    @property
    def is_running(self) -> bool:
        return self._bus is not None and self._bus._dispatch_task is not None and not self._bus._dispatch_task.done()

    @property
    def store(self) -> SQLiteMetadataStore:
        return self._store

    @property
    def objects(self) -> MemoryObjectStore | FileObjectStore:
        return self._objects

    @property
    def heartbeat(self) -> HeartbeatRuntime:
        return self._heartbeat

    async def start(self) -> None:
        """Start the circuit.

        Injects kernel services into all nodes, starts the event bus
        dispatch loop, bootstraps the heartbeat, and starts all node
        coroutines.
        """
        if self.is_running:
            logger.warning("Circuit already running, ignoring duplicate start")
            return

        # Inject kernel services into nodes
        for node in self._nodes:
            node._bus = self._bus
            node._store = self._store
            node._objects = self._objects
            node._lock_client = LockClient(self._store, node.id)

        self._bus.start_dispatch()

        # Bootstrap heartbeat: publish initial tick event
        self._bootstrap_heartbeat()

        for node in self._nodes:
            task = asyncio.create_task(node.run())
            self._node_tasks.append(task)

        logger.info(
            "Circuit started: %d nodes, %s",
            len(self._nodes),
            ", ".join(f"{node.name}({node.id})" for node in self._nodes),
        )

    async def stop(self) -> None:
        """Stop the circuit.

        Terminates all nodes, cancels coroutines, and shuts down
        the event bus dispatch loop.
        """
        if not self.is_running:
            return

        # Terminate nodes
        for node in self._nodes:
            node.state = NodeState.TERMINATED
            node._ready_event.set()

        # Shutdown event bus
        await self._bus.shutdown()

        # Cancel node tasks
        for task in self._node_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._node_tasks, return_exceptions=True)

        self._node_tasks.clear()
        logger.info("Circuit stopped")

    def inject_event(self, event: FileEvent) -> None:
        """Inject an external file event into the circuit.

        The event enters the bus queue; matching nodes are activated.
        """
        if self._bus is None:
            msg = "Circuit not started, cannot inject event"
            raise RuntimeError(msg)
        self._bus.publish(event)

    async def apply_update(self, update: FileUpdate, node_id: str = "system") -> None:
        """Write a file update and trigger downstream events.

        This is the external entry point for file writes (used by
        MCP event bridge and console commands).
        """
        if self._bus is None:
            msg = "Circuit not started, cannot apply update"
            raise RuntimeError(msg)
        await self._bus.apply_update(update, node_id)

    def _bootstrap_heartbeat(self) -> None:
        """Create initial heartbeat tick and inject the first event."""
        heartbeat_dir = Config.KERNEL_DATA_DIR / "heartbeat"
        heartbeat_dir.mkdir(parents=True, exist_ok=True)
        tick_path = heartbeat_dir / "tick.json"

        tick_data = {
            "tick_id": "bootstrap",
            "timestamp": time.time(),
            "interval_sec": 60,
        }
        tick_path.write_text(
            json.dumps(tick_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if self._bus is not None:
            self._bus.publish(
                FileEvent(
                    path="heartbeat/tick.json",
                    change_type="write",
                    metadata={"source_node": "circuit_bootstrap"},
                )
            )
        logger.debug("Heartbeat initial pulse injected")

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()
