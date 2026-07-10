"""AuroraBot Kernel — graph-based file processing engine with CAS locking.

This kernel replaces the previous direct-filesystem kernel with:
- CAS-based distributed locking (SQLiteMetadataStore + LockClient)
- Immutable content-addressed object storage (FileObjectStore)
- Graph-based file flow routing (GraphRuntime + FlowWorker)
- Adaptive load-aware heartbeat (HeartbeatRuntime)
- Enhanced event bus with hook system (FileEventBus + HookRegistry)
"""

from src.kernel.base import (
    Agent,
    FileDescriptor,
    FileEvent,
    FilePattern,
    FileUpdate,
    LockPolicy,
    Node,
    NodeState,
    Router,
)
from src.kernel.event_bus import (
    FileEventBus,
)
from src.kernel.graph import (
    FlowWorker,
    GraphRuntime,
    Route,
)
from src.kernel.heartbeat import (
    HeartbeatRuntime,
    HeartbeatSnapshot,
    LoadSample,
)
from src.kernel.hooks import (
    HookRegistry,
    hook_registry,
)
from src.kernel.locks import (
    LockClient,
)
from src.kernel.metadata import (
    SQLiteMetadataStore,
)
from src.kernel.models import (
    CasConflict,
    FileMeta,
    FileState,
    LockDenied,
)
from src.kernel.objectstore import (
    FileObjectStore,
    MemoryObjectStore,
)
from src.kernel.runner import (
    GraphRunner,
    RunnerCycle,
    RunnerEvent,
)

__all__ = [
    "Agent",
    "CasConflict",
    "FileDescriptor",
    "FileEvent",
    "FileEventBus",
    "FileMeta",
    "FileObjectStore",
    "FilePattern",
    "FileState",
    "FileUpdate",
    "FlowWorker",
    "GraphRunner",
    "GraphRuntime",
    "HeartbeatRuntime",
    "HeartbeatSnapshot",
    "HookRegistry",
    "LoadSample",
    "LockClient",
    "LockDenied",
    "LockPolicy",
    "MemoryObjectStore",
    "Node",
    "NodeState",
    "Route",
    "Router",
    "RunnerCycle",
    "RunnerEvent",
    "SQLiteMetadataStore",
    "hook_registry",
]
