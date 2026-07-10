"""Core abstractions for the AuroraBot cognitive topology circuit.

Node, Agent, and Router base classes, plus file event/update/descriptor types.

All nodes interact with the kernel through the shared metadata store
(SQLiteMetadataStore) and object store (FileObjectStore), rather than
direct filesystem operations.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any

from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

if TYPE_CHECKING:
    from src.kernel.event_bus import FileEventBus
    from src.kernel.locks import LockClient
    from src.kernel.metadata import SQLiteMetadataStore
    from src.kernel.objectstore import FileObjectStore, MemoryObjectStore
    from src.memory import UnifiedMemoryManager

logger = get_logger("NodeBase")


class NodeState(Enum):
    IDLE = auto()
    READY = auto()
    RUNNING = auto()
    WAITING = auto()
    ERROR = auto()
    TERMINATED = auto()


class LockPolicy:
    """File lock strategy constants.

    In the new kernel, these map to CAS-based lock operations:
    - READ_ONLY → LockClient.acquire_read()
    - WRITE_OVERWRITE → LockClient.acquire_write() + release_write()
    - APPEND_ONLY → successive object store puts

    LockPolicy is retained for backward compatibility with existing
    node implementations.
    """

    READ_ONLY = "read_only"
    WRITE_OVERWRITE = "write_overwrite"
    APPEND_ONLY = "append_only"

    @staticmethod
    def locked_by(node_id: str) -> str:
        return f"locked_by_{node_id}"


@dataclass(slots=True)
class FileDescriptor:
    """File descriptor — identifies a file by path, schema, and lock strategy."""

    path: str
    schema: str = "json"
    lock: str = LockPolicy.WRITE_OVERWRITE

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FileDescriptor):
            return NotImplemented
        return self.path == other.path


@dataclass(slots=True)
class FilePattern:
    """File pattern — matches file paths with glob-style patterns."""

    pattern: str

    def match(self, file_path: str) -> bool:
        return fnmatch(file_path, self.pattern)


@dataclass(slots=True)
class FileEvent:
    """File event — notifies nodes of file changes."""

    path: str
    change_type: str
    timestamp: str = field(default_factory=now_text)
    version: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FileUpdate:
    """File update — describes a file change to be written."""

    descriptor: FileDescriptor
    content: Any
    mode: str = "overwrite"


class Node:
    """Atomic unit in the cognitive topology circuit.

    Each Node guards a set of files (guards).  When those files change,
    a FileEvent activates the node, which executes cognitive operations
    and produces new file changes (produces).

    Unlike the old kernel, data reads/writes go through:
    - ``self._store`` (:class:`SQLiteMetadataStore`) — file metadata
    - ``self._objects`` (:class:`FileObjectStore`) — file content
    - ``self._lock`` (:class:`LockClient`) — CAS-based lock operations
    """

    _default_guards: list[str] = []
    _default_produces: list[str] = []

    def __init__(self, node_id: str) -> None:
        self.id = node_id
        self.state = NodeState.IDLE
        self._ready_event: asyncio.Event = asyncio.Event()
        self._bus: FileEventBus | None = None
        self._store: SQLiteMetadataStore | None = None
        self._objects: MemoryObjectStore | FileObjectStore | None = None
        self._lock_client: LockClient | None = None
        self._config_watch: list[str] | None = None
        self._config_emit: list[str] | None = None

    @property
    @abstractmethod
    def type(self) -> str:
        """Return ``"agent"`` (LLM cognitive) or ``"router"`` (pure logic)."""
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def guards(self) -> list[FilePattern]:
        patterns = self._config_watch if self._config_watch is not None else self._default_guards
        return [FilePattern(p) for p in patterns]

    @property
    def produces(self) -> list[FileDescriptor]:
        paths = self._config_emit if self._config_emit is not None else self._default_produces
        return [FileDescriptor(p) for p in paths]

    @property
    def lock(self) -> LockClient:
        if self._lock_client is None:
            msg = f"lock client not injected into node {self.id}"
            raise RuntimeError(msg)
        return self._lock_client

    @property
    def store(self) -> SQLiteMetadataStore:
        if self._store is None:
            msg = f"metadata store not injected into node {self.id}"
            raise RuntimeError(msg)
        return self._store

    @property
    def objects(self) -> MemoryObjectStore | FileObjectStore:
        if self._objects is None:
            msg = f"object store not injected into node {self.id}"
            raise RuntimeError(msg)
        return self._objects

    def on_event(self, event: FileEvent) -> bool:
        """Determine whether this node should be activated by the given event.

        Default implementation matches event path against guards.
        Skips self-produced events to prevent self-triggering.
        """
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        if event.metadata.get("source_node") == self.id:
            return False
        return any(guard.match(event.path) for guard in self.guards)

    def wake(self) -> None:
        """Mark node as READY and wake the run() coroutine."""
        self.state = NodeState.READY
        self._ready_event.set()

    @abstractmethod
    async def execute(self) -> list[FileUpdate]:
        """Execute cognitive operations.

        For Agent, this typically invokes the LLM and produces result files.
        For Router, this executes pure logic and produces file changes.

        Returns the list of FileUpdates produced by this execution step.
        """
        raise NotImplementedError

    def on_complete(self) -> None:
        """Lifecycle hook after execution completes.

        Default resets state to IDLE. Subclasses may override to stay
        in READY state for subsequent events.
        """
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

    async def run(self) -> None:
        """Node main loop.

        Managed as an asyncio.Task by the Circuit.  Waits for the
        ready event, executes, and persists FileUpdates via the bus.
        """
        while self.state != NodeState.TERMINATED:
            try:
                await self._ready_event.wait()
            except asyncio.CancelledError:
                return
            self._ready_event.clear()

            if self.state == NodeState.TERMINATED:
                return

            self.state = NodeState.RUNNING
            try:
                updates = await self.execute()
            except asyncio.CancelledError:
                if self.state == NodeState.TERMINATED:
                    return
                self.on_complete()
                continue
            except Exception:
                logger.exception("Node %s(%s) execution error", self.name, self.id)
                self.state = NodeState.ERROR
                continue

            if self._bus is not None:
                for update in updates:
                    try:
                        await self._bus.apply_update(update, self.id)
                    except Exception:
                        logger.exception(
                            "Node %s(%s) write error: %s",
                            self.name,
                            self.id,
                            update.descriptor.path,
                        )

            self.on_complete()


class Agent(Node):
    """LLM-driven cognitive node.

    Each Agent holds a system prompt and optionally a memory manager
    and host reference.  Execute invokes the LLM via the gateway.
    """

    def __init__(
        self,
        node_id: str,
        host: object | None = None,
        *,
        system_prompt: str = "",
        memory: UnifiedMemoryManager | None = None,
    ) -> None:
        super().__init__(node_id)
        self._host = host
        self._system_prompt = system_prompt
        self._memory = memory
        self._current_gen_task: Any = None

    @property
    def type(self) -> str:
        return "agent"

    @property
    def host(self) -> object | None:
        return self._host

    @host.setter
    def host(self, value: object | None) -> None:
        self._host = value

    @property
    def memory(self) -> UnifiedMemoryManager | None:
        return self._memory

    @memory.setter
    def memory(self, value: UnifiedMemoryManager | None) -> None:
        self._memory = value

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

    async def think(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Invoke the LLM gateway for reasoning."""
        from src.ai.gateway import gateway

        if self._system_prompt:
            messages = [
                {"role": "system", "content": self._system_prompt},
                *messages,
            ]

        gen = gateway.fast.acompletion(messages, **kwargs)
        self._current_gen_task = gen
        try:
            _ = await gen
            return gen.plain()
        finally:
            self._current_gen_task = None

    def cancel_think(self) -> bool:
        """Cancel the current LLM inference if running."""
        gen = self._current_gen_task
        if gen is not None and not gen.done():
            from src.ai.gateway import gateway

            return gateway.abort_task(gen.task_id)
        return False


class Router(Node):
    """Pure logic node — zero LLM calls, predictable execution time.

    Subclasses implement execute() with pure computation and return
    file changes.  Router is the native carrier for flow control:
    conditional branches, multi-way merges, cycle control, etc.
    """

    def __init__(
        self,
        node_id: str,
        host: object | None = None,
        *,
        memory: UnifiedMemoryManager | None = None,
    ) -> None:
        super().__init__(node_id)
        self._host = host
        self._memory = memory

    @property
    def type(self) -> str:
        return "router"

    @property
    def host(self) -> object | None:
        return self._host

    @property
    def memory(self) -> UnifiedMemoryManager | None:
        return self._memory

    @memory.setter
    def memory(self, value: UnifiedMemoryManager | None) -> None:
        self._memory = value

    def on_event(self, event: FileEvent) -> bool:
        return super().on_event(event)
