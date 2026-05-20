from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from src.brain.kernel.circuit import Circuit
from src.brain.kernel.base import Node
from src.brain.nodes.agents import (
    ExampleAgent,
    ExecuteAgent,
    ExpandAgent,
    GoalGeneratorAgent,
    PlanAgent,
    ReflexLearnerAgent,
)
from src.brain.nodes.routers import (
    FanOutRouter,
    HeartbeatRouter,
    MemoryAgent,
    MergeRouter,
    ReflexRouter,
    SwitchRouter,
    TerminalRouter,
)
from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("NodeFactory")

# 节点注册表 —— 新节点加在这里
NODE_REGISTRY: dict[str, type[Node]] = {
    "planner": PlanAgent,
    "expander": ExpandAgent,
    "executor": ExecuteAgent,
    "example": ExampleAgent,
    "fanout": FanOutRouter,
    "switch": SwitchRouter,
    "terminal": TerminalRouter,
    "merge": MergeRouter,
    "heartbeat": HeartbeatRouter,
    "goal_generator": GoalGeneratorAgent,
    "reflex": ReflexRouter,
    "reflex_learner": ReflexLearnerAgent,
    "memory": MemoryAgent,
}

# 节点构造时是否需要 host 引用（按 type 判断）
NODE_NEEDS_HOST: frozenset[str] = frozenset(
    {
        "expander",
        "executor",
        "example",
    }
)

# 节点构造时是否接收 **config 参数（按 type 判断）
NODE_ACCEPTS_CONFIG: frozenset[str] = frozenset(
    {
        "fanout",
        "switch",
        "terminal",
        "merge",
        "heartbeat",
        "goal_generator",
        "reflex",
        "reflex_learner",
        "memory",
    }
)


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
                "config": (
                    entry.get("config", {})
                    if isinstance(entry.get("config"), dict)
                    else {}
                ),
            }
        )
    return normalized


# ── 电路构建 ──────────────────────────────────────


def build_circuit(host: ApplicationHost) -> Circuit:  # noqa: F821
    """从 ``topology.yaml`` 读取配置，构造认知拓扑电路。

    遍历邻接表条目，逐条实例化节点并注入 ``Circuit``。
    同类型可多实例（不同 id/watch/emit/config）。

    Parameters
    ----------
    host : ApplicationHost
        应用宿主，注入给需要访问命令/事件的节点。

    Returns
    -------
    Circuit
        已装配但**未启动**的电路实例，调用方需 await ``circuit.start()``。
    """
    topology = _load_topology_config()
    instances: list[Node] = []

    for entry in topology:
        node_id = entry["id"]
        node_type = entry["type"]
        node_config = entry.get("config", {})

        if not entry.get("enabled", False):
            logger.info(f"节点已禁用: {node_id} ({node_type})")
            continue

        node_cls = NODE_REGISTRY[node_type]

        # 构造 —— 按类型的构造函数签名分发
        if node_type in NODE_ACCEPTS_CONFIG:
            node = node_cls(node_id, **node_config)
        elif node_type in NODE_NEEDS_HOST:
            node = node_cls(node_id, host)
        else:
            node = node_cls(node_id)

        # 覆盖 guards / produces（可选，来自邻接表条目的 watch / emit）
        if entry.get("watch") is not None:
            node._config_watch = entry["watch"]
        if entry.get("emit") is not None:
            node._config_emit = entry["emit"]

        instances.append(node)
        logger.info(f"节点已装配: {node_id} ({node_cls.__name__})")

    if not instances:
        logger.warning("电路没有装配任何节点 — 空转")

    return Circuit(instances)
