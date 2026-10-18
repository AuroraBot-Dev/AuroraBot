"""通过时序消息、节点循环状态和邻域聚合实现记忆推荐。"""

from __future__ import annotations

import math
import threading
from copy import deepcopy
from io import BytesIO
from typing import TYPE_CHECKING

import torch
from torch import Tensor, nn

from src.contracts.memory_checkpoint import MemoryGraphPrefix
from src.contracts.memory_graph import MEMORY_NODE_KINDS, MEMORY_RELATIONS, MemoryNode
from src.contracts.memory_graph_codec import interactions_fingerprint
from src.contracts.model_artifact import model_content_ref
from src.contracts.resource import ResourceRef
from src.memory_model.checkpoint import decode_state, encode_state
from src.memory_model.coordinates import TGN_KEY, TIME_SCALE
from src.memory_model.state import GraphState
from src.utils.features import TEXT_FEATURE_SCHEMA, text_vector

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from pathlib import Path

    from src.contracts.memory_checkpoint import MemoryPolicyCheckpoint
    from src.contracts.memory_graph import MemoryInteraction, MemoryRankingRequest


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
        return self.rank(request, self.project(request.interactions))

    def project(self, interactions: Iterable[MemoryInteraction], state: GraphState | None = None) -> GraphState:
        """按给定顺序更新显式图状态，训练默认从空状态开始。"""
        if state is None:
            state = GraphState()
        for event in interactions:
            self.update(state, event)
        return state

    def rank(self, request: MemoryRankingRequest, state: GraphState) -> Tensor:
        """候选、问题、焦点和读取时间只影响当前评分，不推进历史节点状态。"""
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
    """固定权重增量投影同一图前缀，其他历史分支独立重建。"""

    def __init__(self, network: TemporalMemoryNetwork, revision: str) -> None:
        """绑定实际模型资源版本。"""
        self._network = deepcopy(network).cpu().eval().requires_grad_(False)
        self._ref = ResourceRef(TGN_KEY, revision)
        self._interactions: tuple[MemoryInteraction, ...] | None = ()
        self._prefix: MemoryGraphPrefix | None = None
        self._state = GraphState()
        self._lock = threading.Lock()

    @property
    def ref(self) -> ResourceRef:
        """返回实际权重内容的身份。"""
        return self._ref

    @property
    def parameters(self) -> dict[str, int]:
        """公开编码维度，词项和时间坐标由模型格式统一声明。"""
        return {"hidden_size": self._network.hidden_size, "text_dimensions": self._network.text_dimensions}

    def score(self, request: MemoryRankingRequest) -> tuple[float, ...]:
        """完整前缀一致才复用，较短查询不回退缓存，失败后丢弃未确认状态。"""
        with self._lock, torch.no_grad():
            self._verify_restored(request)
            assert self._interactions is not None
            previous = len(self._interactions)
            extends = len(request.interactions) >= previous and request.interactions[:previous] == self._interactions
            state = self._state if extends else GraphState()
            start = previous if extends else 0
            complete = False
            try:
                self._network.project(request.interactions[start:], state)
                scores = tuple(self._network.rank(request, state).tolist())
                if len(scores) != len(request.candidates) or any(not math.isfinite(score) for score in scores):
                    raise ValueError("时序图记忆模型返回了无效评分")
                if extends or len(request.interactions) > previous:
                    self._state = state
                    self._interactions = request.interactions
                    if len(request.interactions) != previous or not extends:
                        self._prefix = None
                complete = True
                return scores
            finally:
                state.features.clear()
                if not complete:
                    self._clear()

    def checkpoint(self, *, after: str | None = None) -> MemoryPolicyCheckpoint | None:
        """只保存已经过实际历史验证的投影，相同前缀不重复编码。"""
        with self._lock, torch.no_grad():
            if not self._interactions:
                return None
            if self._prefix is None:
                last = self._interactions[-1]
                self._prefix = MemoryGraphPrefix(
                    len(self._interactions), last.cursor, last.recorded_at, interactions_fingerprint(self._interactions)
                )
            if self._prefix.digest == after:
                return None
            state = self._state.snapshot()
            prefix = self._prefix
        return encode_state(state, self.ref, prefix, **self.parameters)

    def restore(self, checkpoint: MemoryPolicyCheckpoint) -> bool:
        """有效载入只暂存状态，第一份实际查询必须再核对完整历史前缀。"""
        state = decode_state(checkpoint, self.ref, **self.parameters)
        if state is None:
            return False
        with self._lock:
            self._state = state
            self._interactions = None
            self._prefix = checkpoint.prefix
        return True

    def _verify_restored(self, request: MemoryRankingRequest) -> None:
        """旧查询、范围变化或世界分支不匹配时，从空投影开始。"""
        if self._interactions is not None:
            return
        prefix = self._prefix
        assert prefix is not None
        events = request.interactions[: prefix.count]
        if (
            len(events) == prefix.count
            and events[-1].cursor == prefix.cursor
            and events[-1].recorded_at == prefix.recorded_at
            and interactions_fingerprint(events) == prefix.digest
        ):
            self._interactions = events
        else:
            self._clear()

    def _clear(self) -> None:
        """计算失败和未确认历史不能留下可再次复用的部分状态。"""
        self._state = GraphState()
        self._interactions = ()
        self._prefix = None


def load_policy(path: Path) -> TGNMemoryPolicy:
    """只接受张量及基础元数据，拒绝关系或时间编码不兼容的权重。"""
    return load_policy_bytes(path.read_bytes())


def load_policy_bytes(content: bytes, *, expected: ResourceRef | None = None) -> TGNMemoryPolicy:
    """解码同一份确定版本的模型字节，不依赖加载过程中仍存在的路径。"""
    ref = model_content_ref(content, TGN_KEY, expected)
    assert ref.revision is not None
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
    return TGNMemoryPolicy(network, ref.revision)


def _interval(now: datetime, previous: datetime) -> float:
    """使用真实获知间隔，不把迟到事件的发生时间当成状态更新时间。"""
    return math.log1p(max(0.0, (now - previous).total_seconds())) / TIME_SCALE
