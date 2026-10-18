"""时序图记忆模型的真实 CPU 训练、独立验证和权重导出。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from itertools import combinations
from typing import TYPE_CHECKING, Any

import torch
from torch import Tensor, nn

from src.contracts.memory_graph import MEMORY_NODE_KINDS, MEMORY_RELATIONS
from src.contracts.model_artifact import model_content_ref
from src.contracts.training import bind_training_provenance, provenance_data
from src.memory_model.dataset import MemoryEpisode, episodes_fingerprint, validate_partition
from src.memory_model.evaluation import evaluate_policy
from src.memory_model.rules import RuleMemoryPolicy
from src.memory_model.tgn import TGN_KEY, TIME_SCALE, TemporalMemoryNetwork, TGNMemoryPolicy
from src.utils.features import TEXT_FEATURE_SCHEMA

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.resource import ResourceRef
    from src.contracts.training import TrainingProvenance
    from src.memory_model.dataset import MemoryExample


@dataclass(frozen=True, slots=True)
class MemoryTrainingResult:
    """训练轨迹、模型参数和完整独立经历上的比较结果。"""

    network: TemporalMemoryNetwork
    losses: tuple[float, ...]
    metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    parameters: dict[str, float | int]
    training_episodes: tuple[str, ...]
    validation_episodes: tuple[str, ...]
    provenance: TrainingProvenance

    def save(self, path: Path) -> ResourceRef:
        """权重只含张量和基础元数据；动态节点状态始终从经历恢复。"""
        content = self.to_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return model_content_ref(content, TGN_KEY)

    def to_bytes(self) -> bytes:
        """同一份归档用于模型资源和文件导出，版本不依赖输出路径。"""
        data: dict[str, Any] = {
            "schema_version": 1,
            "model_key": str(TGN_KEY),
            "relations": list(MEMORY_RELATIONS),
            "node_kinds": list(MEMORY_NODE_KINDS),
            "time_scale": TIME_SCALE,
            "text_features": TEXT_FEATURE_SCHEMA,
            "hidden_size": self.network.hidden_size,
            "text_dimensions": self.network.text_dimensions,
            "state_dict": self.network.state_dict(),
            "training": {
                "losses": list(self.losses),
                "metrics": self.metrics,
                "baseline_metrics": self.baseline_metrics,
                "parameters": self.parameters,
                "framework": {"name": "pytorch", "version": str(torch.__version__), "device": "cpu"},
                "training_episodes": list(self.training_episodes),
                "validation_episodes": list(self.validation_episodes),
                "data": provenance_data(self.provenance),
            },
        }
        stream = BytesIO()
        torch.save(data, stream)
        return stream.getvalue()


def train(
    training: tuple[MemoryEpisode, ...],
    validation: tuple[MemoryEpisode, ...],
    *,
    hidden_size: int = 16,
    text_dimensions: int = 32,
    epochs: int = 100,
    learning_rate: float = 0.01,
    seed: int = 0,
    provenance: TrainingProvenance | None = None,
) -> MemoryTrainingResult:
    """按效用差加权成对排序，较晚验证经历不会参与梯度计算。"""
    validate_partition(training, validation)
    provenance = bind_training_provenance(
        "memory", episodes_fingerprint(training), episodes_fingerprint(validation), provenance
    )
    if epochs <= 0 or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("训练轮数和学习率必须为正数")
    batches = tuple((example, _pairs(example)) for episode in training for example in episode.examples)
    total_weight = sum(float(weights.sum()) for _example, (_left, _right, _signs, weights) in batches)
    if total_weight <= 0:
        raise ValueError("训练样本需要至少一组效用不同的候选")
    losses: list[float] = []
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        network = TemporalMemoryNetwork(hidden_size, text_dimensions)
        optimizer = torch.optim.Adam(network.parameters(), lr=learning_rate)
        for _ in range(epochs):
            total = 0.0
            optimizer.zero_grad()
            for example, (left, right, signs, weights) in batches:
                if weights.numel() == 0:
                    continue
                scores = network(example.request)
                loss = (nn.functional.softplus(-(scores[left] - scores[right]) * signs) * weights).sum() / total_weight
                if not bool(torch.isfinite(loss).item()):
                    raise ValueError("记忆训练损失不是有限数值")
                loss.backward()
                total += float(loss.item())
            nn.utils.clip_grad_norm_(network.parameters(), max_norm=5, error_if_nonfinite=True)
            optimizer.step()
            losses.append(total)
    network.eval()
    return MemoryTrainingResult(
        network,
        tuple(losses),
        evaluate_policy(TGNMemoryPolicy(network, "evaluation"), validation),
        evaluate_policy(RuleMemoryPolicy(), validation),
        {
            "hidden_size": hidden_size,
            "text_dimensions": text_dimensions,
            "epochs": epochs,
            "learning_rate": learning_rate,
            "seed": seed,
        },
        tuple(episode.episode_id for episode in training),
        tuple(episode.episode_id for episode in validation),
        provenance,
    )


def _pairs(example: MemoryExample) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    """监督值只产生损失权重，不进入候选文本、节点状态或图边。"""
    pairs = tuple(
        (left, right, example.utilities[left] - example.utilities[right])
        for left, right in combinations(range(len(example.utilities)), 2)
        if example.utilities[left] != example.utilities[right]
    )
    return (
        torch.tensor([left for left, _right, _difference in pairs], dtype=torch.long),
        torch.tensor([right for _left, right, _difference in pairs], dtype=torch.long),
        torch.tensor([1.0 if difference > 0 else -1.0 for _left, _right, difference in pairs]),
        torch.tensor([abs(difference) for _left, _right, difference in pairs]),
    )
