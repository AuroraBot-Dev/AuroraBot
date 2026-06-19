from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import yaml

from src.brain.kernel.circuit import Circuit
from src.brain.nodes.agents import (
    ActionPlanner,
    Externalizer,
    ImpulseGate,
    Internalizer,
    MemoryConsolidator,
    PolarisAgent,
)
from src.brain.nodes.routers import (
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
from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.brain.kernel.base import Node
    from src.brain.memory import UnifiedMemoryManager

logger = get_logger("NodeFactory")

# 节点注册表 —— 新节点加在这里
NODE_REGISTRY: dict[str, type[Node]] = {
    # Kernel-gamma 认知管线（两池 + 两转义者 + MCP 工具派发）
    "message_preprocessor": MessagePreprocessor,
    "internalizer": Internalizer,
    "externalizer": Externalizer,
    "mcp_tool_dispatcher": MCPToolDispatcher,
    # 节律系统
    "heartbeat_generator": HeartbeatGenerator,
    "timer_scheduler": TimerScheduler,
    # 记忆沉淀 & 可观测性
    "memory_consolidator": MemoryConsolidator,
    "metrics_collector": MetricsCollector,
    # 拓扑原语
    "switch_router": SwitchRouter,
    "merge_router": MergeRouter,
    "broadcast_router": BroadcastRouter,
    "dead_letter_router": DeadLetterRouter,
    # Kernel-beta 旧节点（disabled）
    "impulse_gate": ImpulseGate,
    "action_planner": ActionPlanner,
    # 旧单体节点（兼容模式）
    "polaris": PolarisAgent,
}

# 节点构造时是否需要 host 引用（按 type 判断）
NODE_NEEDS_HOST: frozenset[str] = frozenset(
    {
        "internalizer",
        "externalizer",
    }
)

# 节点构造时是否需要 client_manager 引用（按 type 判断）
NODE_NEEDS_CLIENT_MANAGER: frozenset[str] = frozenset(
    {
        "mcp_tool_dispatcher",
        "externalizer",
    }
)

# 节点构造时是否接收 **config 参数（按 type 判断）
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

# 节点构造时是否注入 UnifiedMemoryManager（按 type 判断）
NODE_NEEDS_MEMORY: frozenset[str] = frozenset()


# ── 拓扑配置加载 ──────────────────────────────────


def _load_topology_config() -> list[dict[str, Any]]:
    """读取 ``topology.yaml``，返回归一化的节点配置列表。"""
    path = Config.TOPOLOGY_CONFIG
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning(f"拓扑配置不存在: {path}，使用全量默认配置")
        return _default_topology()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"读取拓扑配置失败: {exc}，使用全量默认配置")
        return _default_topology()

    if not isinstance(payload, dict):
        logger.warning("拓扑配置格式错误，使用全量默认配置")
        return _default_topology()

    raw_nodes = payload.get("nodes")
    if isinstance(raw_nodes, list):
        return _normalize_list(raw_nodes)

    logger.warning("拓扑配置缺少 nodes 字段或格式错误，使用全量默认配置")
    return _default_topology()


def _default_topology() -> list[dict[str, Any]]:
    """全量启用所有注册节点，各一个实例（id=类型名）。"""
    return [{"id": name, "type": name} for name in sorted(NODE_REGISTRY)]


def _normalize_list(raw_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归一化新版 list 格式，未知 type 丢弃。"""
    normalized: list[dict[str, Any]] = []
    for i, entry in enumerate(raw_nodes):
        if not isinstance(entry, dict):
            continue
        node_type = entry.get("type")
        if node_type not in NODE_REGISTRY:
            logger.warning(f"拓扑配置包含未知节点类型: {node_type!r}，已忽略")
            continue
        normalized.append(
            {
                "id": str(entry.get("id", f"{node_type}-{i}")),
                "type": node_type,
                "enabled": bool(entry.get("enabled", True)),
                "watch": entry.get("watch"),  # None = 不覆盖，沿用类默认值
                "emit": entry.get("emit"),  # None = 不覆盖，沿用类默认值
                "config": (entry.get("config", {}) if isinstance(entry.get("config"), dict) else {}),
            }
        )
    return normalized


# ── 电路构建 ──────────────────────────────────────


def build_circuit(  # noqa: C901
    host: object | None = None,
    client_manager: Any | None = None,
) -> Circuit:
    """从 ``topology.yaml`` 读取配置，构造认知拓扑电路。

    遍历邻接表条目，逐条实例化节点并注入 ``Circuit``。
    同类型可多实例（不同 id/watch/emit/config）。

    Parameters
    ----------
    host : object | None
        上下文对象（可选），注入给需要它的节点。
    client_manager : MCPClientManager | None
        MCP 客户端管理器，注入给需要执行工具调用的节点。

    Returns
    -------
    Circuit
        已装配但**未启动**的电路实例，调用方需 await ``circuit.start()``。
    """
    topology = _load_topology_config()
    instances: list[Node] = []
    memory_manager: UnifiedMemoryManager | None = None

    for entry in topology:
        node_id = entry["id"]
        node_type = entry["type"]
        node_config = entry.get("config", {})

        if not entry.get("enabled", False):
            logger.info(f"节点已禁用: {node_id} ({node_type})")
            continue

        node_cls = NODE_REGISTRY[node_type]
        if node_type in NODE_NEEDS_MEMORY:
            if memory_manager is None:
                from src.brain.memory import get_memory_manager

                memory_manager = get_memory_manager()
            memory_kw = {"memory": memory_manager}
        else:
            memory_kw = {}

        # 构造 —— 按类型的构造函数签名分发
        node_ctor = cast("Callable[..., object]", node_cls)
        if node_type in NODE_ACCEPTS_CONFIG:
            node = cast("Node", node_ctor(node_id, **node_config, **memory_kw))
        elif node_type in NODE_NEEDS_CLIENT_MANAGER:
            node = cast("Node", node_ctor(node_id, client_manager, **memory_kw))
        elif node_type in NODE_NEEDS_HOST:
            node = cast("Node", node_ctor(node_id, host, **memory_kw))
        else:
            node = cast("Node", node_ctor(node_id, **memory_kw))

        # 覆盖 guards / produces（可选，来自邻接表条目的 watch / emit）
        if entry.get("watch") is not None:
            node._config_watch = entry["watch"]
        if entry.get("emit") is not None:
            node._config_emit = entry["emit"]

        instances.append(node)
        logger.info(f"节点已装配: {node_id} ({node_cls.__name__}): {node._config_watch} -> {node._config_emit}")

    if not instances:
        logger.warning("电路没有装配任何节点")

    return Circuit(instances)
