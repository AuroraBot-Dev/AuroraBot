"""通过时序消息、节点循环状态和邻域聚合实现记忆推荐。"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from io import BytesIO
from typing import TYPE_CHECKING

import torch
from torch import Tensor, nn

from src.contracts.memory_graph import MEMORY_NODE_KINDS, MEMORY_RELATIONS, MemoryNode
from src.contracts.resource import ResourceKey, ResourceRef
from src.utils.features import TEXT_FEATURE_SCHEMA, text_vector

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from src.contracts.memory_graph import MemoryInteraction, MemoryRankingRequest

TGN_KEY = ResourceKey.parse("aurora:memory/model/tgn")
TIME_SCALE = 20.0
type NodeKey = tuple[str, str]


@dataclass(slots=True)
class GraphState:
    """一次评分重建的节点状态，独立于可训练模型参数。"""

    memories: dict[NodeKey, Tensor] = field(default_factory=dict)
    nodes: dict[NodeKey, MemoryNode] = field(default_factory=dict)
    updated_at: dict[NodeKey, datetime] = field(default_factory=dict)
    neighbors: dict[NodeKey, set[NodeKey]] = field(default_factory=dict)
    features: dict[tuple[NodeKey, str], Tensor] = field(default_factory=dict)


class TemporalMemoryNetwork(nn.Module):
    """用获知间隔更新节点，再以邻域表示推荐一组候选记忆。"""

    def __init__(self, hidden_size: int = 16, text_dimensions: int = 32) -> None:
        """固定文本和关系坐标，所有训练与在线计算共用此实现。"""
        super().__init__()
        if hidden_size <= 0 or text_dimensions <= 0:
            raise ValueError("记忆模型维数必须为正数")
        self.hidden_size = hidden_size
        self.text_dimensions = text_dimensions
        self.node_encoder = nn.Linear(text_dimensions + len(MEMORY_NODE_KINDS), hidden_size)
        self.relation_encoder = nn.Embedding(len(MEMORY_RELATIONS), hidden_size)
        self.message = nn.Sequential(nn.Linear(hidden_size * 5 + 3, hidden_size), nn.Tanh())
        self.recurrent = nn.GRUCell(hidden_size, hidden_size)
        self.embedding = nn.Sequential(nn.Linear(hidden_size * 3 + 1, hidden_size), nn.Tanh())
        self.query_encoder = nn.Linear(text_dimensions, hidden_size)
        self.query_embedding = nn.Sequential(nn.Linear(hidden_size * 2, hidden_size), nn.Tanh())
        self.recommendation = nn.Sequential(
            nn.Linear(hidden_size * 4 + 4, hidden_size), nn.Tanh(), nn.Linear(hidden_size, 1)
        )

    def forward(self, request: MemoryRankingRequest) -> Tensor:
        """先处理已知交互，再评分；本次监督标签不会成为任何图消息。"""
        state = GraphState()
        for event in request.interactions:
            self.update(state, event)
        query_text = self.query_encoder(torch.tensor(text_vector(request.query, self.text_dimensions)))
        focused = tuple(
            self.node_embedding(state, MemoryNode("goal", identity, identity), request.observed_at)
            for identity in request.focus_goal_ids
        )
        goals = torch.stack(focused).mean(0) if focused else self._zero()
        query = self.query_embedding(torch.cat((query_text, goals)))
        scores: list[Tensor] = []
        for item in request.candidates:
            node = MemoryNode("memory", item.memory_id, item.text)
            encoded = self.node_embedding(state, node, request.observed_at)
            age = _interval(request.observed_at, item.occurred_at)
            baseline = torch.tensor((item.similarity, float(item.goal_match), float(item.entity_match), age))
            features = torch.cat((query, encoded, query * encoded, (query - encoded).abs(), baseline))
            scores.append(self.recommendation(features).squeeze(-1))
        return torch.stack(scores) if scores else torch.empty(0)

    def update(self, state: GraphState, event: MemoryInteraction) -> None:
        """两端消息都使用交互前的状态，避免同一条边重复影响另一端。"""
        source, target = event.source, event.target
        first = state.memories.get(source.key, self._zero())
        second = state.memories.get(target.key, self._zero())
        source_feature = self._feature(state, source)
        target_feature = self._feature(state, target)
        relation = self.relation_encoder(torch.tensor(MEMORY_RELATIONS.index(event.relation)))
        first_age = _interval(event.recorded_at, state.updated_at.get(source.key, event.recorded_at))
        second_age = _interval(event.recorded_at, state.updated_at.get(target.key, event.recorded_at))
        value = math.tanh(event.value)
        source_message = self.message(
            torch.cat(
                (first, second, source_feature, target_feature, relation, torch.tensor((first_age, second_age, value)))
            )
        )
        target_message = self.message(
            torch.cat(
                (second, first, target_feature, source_feature, relation, torch.tensor((second_age, first_age, value)))
            )
        )
        state.memories[source.key] = self.recurrent(source_message, first)
        if target.key != source.key:
            state.memories[target.key] = self.recurrent(target_message, second)
            state.neighbors.setdefault(source.key, set()).add(target.key)
            state.neighbors.setdefault(target.key, set()).add(source.key)
        for node in (source, target):
            if node.text or node.key not in state.nodes:
                state.nodes[node.key] = node
            state.updated_at[node.key] = event.recorded_at

    def node_embedding(self, state: GraphState, node: MemoryNode, observed_at: datetime) -> Tensor:
        """结合自身历史、邻居历史、当前可见文本与距离上次活动的时间。"""
        memory = state.memories.get(node.key, self._zero())
        neighbors = tuple(state.memories[key] for key in sorted(state.neighbors.get(node.key, ())))
        neighborhood = torch.stack(neighbors).mean(0) if neighbors else self._zero()
        feature = self._feature(state, state.nodes.get(node.key, node))
        age = _interval(observed_at, state.updated_at.get(node.key, observed_at))
        return self.embedding(torch.cat((memory, neighborhood, feature, torch.tensor((age,)))))

    def _feature(self, state: GraphState, node: MemoryNode) -> Tensor:
        """缓存同一计算图内的文本编码，节点内容更新时使用新的坐标。"""
        key = node.key, node.text
        if key not in state.features:
            kinds = tuple(float(kind == node.kind) for kind in MEMORY_NODE_KINDS)
            features = torch.tensor((*text_vector(node.text, self.text_dimensions), *kinds))
            state.features[key] = self.node_encoder(features).tanh()
        return state.features[key]

    def _zero(self) -> Tensor:
        """新节点从零历史开始，不共享其他 Bot 或样本的隐状态。"""
        return torch.zeros(self.hidden_size)


class TGNMemoryPolicy:
    """固定权重读取可重放的历史图，节点状态不会写入权重文件。"""

    def __init__(self, network: TemporalMemoryNetwork, revision: str) -> None:
        """绑定实际模型资源版本。"""
        self.network = network.cpu().eval()
        self._ref = ResourceRef(TGN_KEY, revision)

    @property
    def ref(self) -> ResourceRef:
        """返回实际权重内容的身份。"""
        return self._ref

    @property
    def parameters(self) -> dict[str, int]:
        """公开编码维度，词项和时间坐标由模型格式统一声明。"""
        return {"hidden_size": self.network.hidden_size, "text_dimensions": self.network.text_dimensions}

    def score(self, request: MemoryRankingRequest) -> tuple[float, ...]:
        """在线读取不更新模型参数，也不保留其他查询的运行状态。"""
        with torch.no_grad():
            return tuple(self.network(request).tolist())


def load_policy(path: Path) -> TGNMemoryPolicy:
    """只接受张量及基础元数据，拒绝关系或时间编码不兼容的权重。"""
    content = path.read_bytes()
    data = torch.load(BytesIO(content), map_location="cpu", weights_only=True)
    if data["schema_version"] != 1 or data["model_key"] != str(TGN_KEY):
        raise ValueError("不支持的时序记忆权重格式")
    if tuple(data["relations"]) != MEMORY_RELATIONS or tuple(data["node_kinds"]) != MEMORY_NODE_KINDS:
        raise ValueError("时序记忆权重的关系坐标不兼容")
    if data["time_scale"] != TIME_SCALE or data["text_features"] != TEXT_FEATURE_SCHEMA:
        raise ValueError("时序记忆权重的时间或文本坐标不兼容")
    network = TemporalMemoryNetwork(data["hidden_size"], data["text_dimensions"])
    network.load_state_dict(data["state_dict"], strict=True)
    if any(not bool(torch.isfinite(parameter).all()) for parameter in network.parameters()):
        raise ValueError("时序记忆权重包含非有限数值")
    return TGNMemoryPolicy(network, hashlib.sha256(content).hexdigest())


def _interval(now: datetime, previous: datetime) -> float:
    """使用真实获知间隔，不把迟到事件的发生时间当成状态更新时间。"""
    return math.log1p(max(0.0, (now - previous).total_seconds())) / TIME_SCALE
