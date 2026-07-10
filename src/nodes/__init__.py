"""AuroraBot cognitive nodes — agents, routers, and event bridge for the kernel circuit."""

from src.nodes.agents import Externalizer, Internalizer, MemoryConsolidator
from src.nodes.event_bridge import run_mcp_event_bridge
from src.nodes.routers import (
    BroadcastRouter,
    DeadLetterRouter,
    HeartbeatGenerator,
    MCPToolDispatcher,
    MergeRouter,
    MessagePreprocessor,
    MetricsCollector,
    SwitchRouter,
    TimerScheduler,
)

__all__ = [
    "BroadcastRouter",
    "DeadLetterRouter",
    "Externalizer",
    "HeartbeatGenerator",
    "Internalizer",
    "MCPToolDispatcher",
    "MemoryConsolidator",
    "MergeRouter",
    "MessagePreprocessor",
    "MetricsCollector",
    "SwitchRouter",
    "TimerScheduler",
    "run_mcp_event_bridge",
]
