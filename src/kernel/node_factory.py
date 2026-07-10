"""Node factory — builds Circuit from topology.yaml with the new kernel backend.

Reads topology configuration, creates node instances, initialises the
storage layer (SQLiteMetadataStore + FileObjectStore), and assembles
the Circuit with GraphRuntime and HeartbeatRuntime.

Usage::

    from src.kernel.node_factory import build_circuit
    circuit = build_circuit(client_manager=client_manager)
    await circuit.start()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import yaml

from src.config import Config
from src.kernel.base import Node
from src.kernel.circuit import Circuit
from src.kernel.event_bus import FileEventBus
from src.kernel.graph import GraphRuntime, Route
from src.kernel.heartbeat import HeartbeatRuntime
from src.kernel.metadata import SQLiteMetadataStore
from src.kernel.objectstore import FileObjectStore
from src.nodes.agents import Externalizer, Internalizer, MemoryConsolidator
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
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.platform.mcp.client_manager import MCPClientManager

logger = get_logger("NodeFactory")

# Node registry — add new node types here
NODE_REGISTRY: dict[str, type[Node]] = {
    "message_preprocessor": MessagePreprocessor,
    "internalizer": Internalizer,
    "externalizer": Externalizer,
    "mcp_tool_dispatcher": MCPToolDispatcher,
    "heartbeat_generator": HeartbeatGenerator,
    "timer_scheduler": TimerScheduler,
    "memory_consolidator": MemoryConsolidator,
    "metrics_collector": MetricsCollector,
    "switch_router": SwitchRouter,
    "merge_router": MergeRouter,
    "broadcast_router": BroadcastRouter,
    "dead_letter_router": DeadLetterRouter,
}

# Nodes that need client_manager at construction time
NODE_NEEDS_CLIENT_MANAGER: frozenset[str] = frozenset(
    {
        "mcp_tool_dispatcher",
        "externalizer",
    }
)

# Nodes that accept **config at construction time
NODE_ACCEPTS_CONFIG: frozenset[str] = frozenset(
    {
        "heartbeat_generator",
        "timer_scheduler",
        "switch_router",
        "merge_router",
        "broadcast_router",
        "dead_letter_router",
    }
)

_DEFAULT_TOPOLOGY: tuple[dict[str, Any], ...] = (
    {
        "id": "message_preprocessor",
        "type": "message_preprocessor",
        "watch": ["inbox/pending/event_*.json"],
        "emit": ["pipeline/message_queue/*.json"],
    },
    {
        "id": "internalizer",
        "type": "internalizer",
        "watch": ["pipeline/message_queue/*.json"],
        "emit": ["pipeline/internalized/*.json"],
    },
    {
        "id": "externalizer",
        "type": "externalizer",
        "watch": ["pipeline/internalized/*.json"],
        "emit": ["pipeline/action_queue/*.json"],
    },
    {
        "id": "mcp_tool_dispatcher",
        "type": "mcp_tool_dispatcher",
        "watch": ["pipeline/action_queue/*.json"],
    },
    {
        "id": "heartbeat",
        "type": "heartbeat_generator",
        "watch": ["heartbeat/tick.json"],
        "emit": ["heartbeat/tick.json"],
        "config": {"interval_sec": 60},
    },
    {
        "id": "timer_scheduler",
        "type": "timer_scheduler",
        "watch": ["heartbeat/tick.json"],
        "emit": ["rhythm/triggers/*.json"],
    },
)


# ── Topology config loading ──────────────────────────


def _load_topology_config() -> list[dict[str, Any]]:
    """Read ``topology.yaml`` and return normalized node config list."""
    path = Config.TOPOLOGY_CONFIG
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Topology config not found: %s, using defaults", path)
        return _default_topology()
    except Exception as exc:
        logger.warning("Failed to read topology config: %s, using defaults", exc)
        return _default_topology()

    if not isinstance(payload, dict):
        logger.warning("Topology config is not a dict, using defaults")
        return _default_topology()

    raw_nodes = payload.get("nodes")
    if isinstance(raw_nodes, list):
        return _normalize_list(raw_nodes)

    logger.warning("Topology config missing 'nodes' field, using defaults")
    return _default_topology()


def _default_topology() -> list[dict[str, Any]]:
    """Return minimal topology for safe startup."""
    return [dict(entry) for entry in _DEFAULT_TOPOLOGY]


def _normalize_list(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize list-format topology, dropping unknown types."""
    normalized: list[dict[str, Any]] = []
    for i, entry in enumerate(raw_nodes):
        if not isinstance(entry, dict):
            continue
        node_type = entry.get("type")
        if node_type not in NODE_REGISTRY:
            logger.warning("Unknown node type in topology: %r, skipping", node_type)
            continue
        normalized.append(
            {
                "id": str(entry.get("id", f"{node_type}-{i}")),
                "type": node_type,
                "enabled": bool(entry.get("enabled", True)),
                "watch": entry.get("watch"),
                "emit": entry.get("emit"),
                "config": entry.get("config", {}) if isinstance(entry.get("config"), dict) else {},
            }
        )
    return normalized


# ── Circuit builder ─────────────────────────────────


def build_circuit(
    *,
    store: SQLiteMetadataStore | None = None,
    objects: FileObjectStore | None = None,
    client_manager: MCPClientManager | None = None,
) -> Circuit:
    """Build the cognitive topology circuit from topology.yaml.

    Creates the storage layer, graph runtime, heartbeat runtime,
    node instances, event bus, and assembles the Circuit.

    Parameters
    ----------
    store : SQLiteMetadataStore, optional
        Reuse an existing metadata store. Created fresh if None.
    objects : FileObjectStore, optional
        Reuse an existing object store. Created fresh if None.
    client_manager : MCPClientManager, optional
        MCP client manager, injected into nodes that need it.

    Returns
    -------
    Circuit
        Assembled but not yet started.
    """
    topology = _load_topology_config()

    # ── Storage layer ──
    kernel_dir = Config.KERNEL_DATA_DIR
    kernel_dir.mkdir(parents=True, exist_ok=True)
    store = store or SQLiteMetadataStore(str(kernel_dir / "meta.sqlite"))
    objects = objects or FileObjectStore(kernel_dir / "objects")

    # ── Build routes from topology ──
    routes = _build_routes(topology)
    graph = GraphRuntime(store, objects, routes)
    heartbeat = HeartbeatRuntime(store, objects)

    # ── Instantiate nodes ──
    instances: list[Node] = []
    for entry in topology:
        node_id = entry["id"]
        node_type = entry["type"]
        node_config = entry.get("config", {})

        if not entry.get("enabled", True):
            logger.info("Node disabled: %s (%s)", node_id, node_type)
            continue

        node_cls = NODE_REGISTRY[node_type]
        node_ctor = cast("Callable[..., object]", node_cls)

        if node_type in NODE_ACCEPTS_CONFIG:
            node = cast("Node", node_ctor(node_id, **node_config))
        elif node_type in NODE_NEEDS_CLIENT_MANAGER:
            node = cast("Node", node_ctor(node_id, client_manager))
        else:
            node = cast("Node", node_ctor(node_id))

        # Override guards/produces from topology config
        if entry.get("watch") is not None:
            node._config_watch = entry["watch"]
        if entry.get("emit") is not None:
            node._config_emit = entry["emit"]

        instances.append(node)
        logger.info(
            "Node assembled: %s (%s): %s -> %s",
            node_id,
            node_cls.__name__,
            node._config_watch,
            node._config_emit,
        )

    if not instances:
        logger.warning("Circuit has no nodes")

    # ── Event bus ──
    bus = FileEventBus(instances, store, objects)

    # ── Circuit ──
    return Circuit(instances, store, objects, heartbeat, bus)


def _build_routes(topology: list[dict[str, Any]]) -> list[Route]:
    """Build Route list from topology node config.

    Each node's watch→emit mapping becomes a Route entry.
    """
    routes: list[Route] = []
    for entry in topology:
        watch = entry.get("watch")
        emit = entry.get("emit")
        if not watch or not emit:
            continue
        for watch_glob in watch:
            input_type = _glob_to_type(watch_glob)
            for emit_path in emit:
                output_type = _glob_to_type(emit_path)
                routes.append(
                    Route(
                        input_type=input_type,
                        output_type=output_type or None,
                        worker_role=entry["type"],
                    )
                )
    return routes


def _glob_to_type(glob_pattern: str) -> str:
    """Convert a glob pattern to a type name.

    e.g. ``inbox/pending/event_*.json`` → ``inbox_pending_event``
         ``heartbeat/tick.json`` → ``heartbeat_tick``
    """
    name = glob_pattern.replace("/", "_").replace("\\", "_")
    # Remove file extension
    if "." in name:
        name = name.rsplit(".", 1)[0]
    # Remove glob wildcards
    name = name.replace("*", "").replace("?", "")
    # Collapse multiple underscores
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_")
