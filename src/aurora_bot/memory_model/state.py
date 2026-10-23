"""由固定权重投影出的动态图状态，与训练参数分开管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from torch import Tensor

    from aurora_bot.contracts.memory_graph import MemoryNode

type NodeKey = tuple[str, str]


@dataclass(slots=True)
class GraphState:
    """一个确切历史前缀的节点投影，特征缓存可以随时重建。"""

    memories: dict[NodeKey, Tensor] = field(default_factory=dict)
    nodes: dict[NodeKey, MemoryNode] = field(default_factory=dict)
    updated_at: dict[NodeKey, datetime] = field(default_factory=dict)
    neighbors: dict[NodeKey, set[NodeKey]] = field(default_factory=dict)
    features: dict[tuple[NodeKey, str], Tensor] = field(default_factory=dict)

    def snapshot(self) -> GraphState:
        """复制节点容器与邻居集合；在线更新始终替换张量，不原地改写旧张量。"""
        return GraphState(
            memories=dict(self.memories),
            nodes=dict(self.nodes),
            updated_at=dict(self.updated_at),
            neighbors={key: set(value) for key, value in self.neighbors.items()},
        )
