"""节律模型的 CPU 训练、时序验证与权重导出。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any

import torch
from torch import Tensor, nn

from src.contracts.model_artifact import model_content_ref
from src.contracts.rhythm import RHYTHM_FEATURES
from src.contracts.training import bind_training_provenance, provenance_data
from src.rhythm.dataset import RhythmEpisode, episodes_fingerprint, validate_partition
from src.rhythm.evaluation import evaluate_policy
from src.rhythm.gru import GRU_KEY, GRURhythmPolicy, RhythmNetwork
from src.rhythm.rules import RuleRhythmPolicy

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.resource import ResourceRef
    from src.contracts.training import TrainingProvenance


@dataclass(frozen=True, slots=True)
class RhythmTrainingResult:
    """训练轨迹和独立较晚经历上的验证结果。"""

    network: RhythmNetwork
    losses: tuple[float, ...]
    metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    parameters: dict[str, float | int]
    training_episodes: tuple[str, ...]
    validation_episodes: tuple[str, ...]
    provenance: TrainingProvenance

    def save(self, path: Path) -> ResourceRef:
        """保存输入坐标、张量和训练来源，不保存可执行对象。"""
        content = self.to_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return model_content_ref(content, GRU_KEY)

    def to_bytes(self) -> bytes:
        """编码一次即可同时发布资源和导出文件，不从可变路径回读计算版本。"""
        data: dict[str, Any] = {
            "schema_version": 1,
            "model_key": str(GRU_KEY),
            "features": list(RHYTHM_FEATURES),
            "hidden_size": self.network.hidden_size,
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
    training: tuple[RhythmEpisode, ...],
    validation: tuple[RhythmEpisode, ...],
    *,
    hidden_size: int = 16,
    epochs: int = 100,
    learning_rate: float = 0.01,
    seed: int = 0,
    provenance: TrainingProvenance | None = None,
) -> RhythmTrainingResult:
    """经历内部反向传播，经历之间重置状态，验证集不参与优化。"""
    validate_partition(training, validation)
    provenance = bind_training_provenance(
        "rhythm", episodes_fingerprint(training), episodes_fingerprint(validation), provenance
    )
    if epochs <= 0 or not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("训练轮数与学习率必须大于零")
    losses: list[float] = []
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        network = RhythmNetwork(hidden_size)
        optimizer = torch.optim.Adam(network.parameters(), lr=learning_rate)
        batches = tuple(_tensors(episode) for episode in training)
        total_utility = sum(float(weights.sum().item()) for _features, _labels, _delays, weights in batches)
        total_examples = sum(labels.numel() for _features, labels, _delays, _weights in batches)
        for _ in range(epochs):
            total = 0.0
            optimizer.zero_grad()
            for features, labels, delays, utility_weights in batches:
                logits, predicted_delays, _hidden = network(features)
                classification = nn.functional.binary_cross_entropy_with_logits(logits, labels, reduction="none")
                loss = (classification * utility_weights).sum() / total_utility
                loss = loss + nn.functional.smooth_l1_loss(predicted_delays, delays, reduction="sum") / total_examples
                if not bool(torch.isfinite(loss).item()):
                    raise ValueError("训练损失不是有限数值，请核对样本与学习率")
                loss.backward()
                total += float(loss.item())
            nn.utils.clip_grad_norm_(network.parameters(), max_norm=5, error_if_nonfinite=True)
            optimizer.step()
            losses.append(total)
    network.eval()
    return RhythmTrainingResult(
        network,
        tuple(losses),
        evaluate_policy(GRURhythmPolicy(network, "evaluation"), validation),
        evaluate_policy(RuleRhythmPolicy(), validation),
        {"hidden_size": hidden_size, "epochs": epochs, "learning_rate": learning_rate, "seed": seed},
        tuple(episode.episode_id for episode in training),
        tuple(episode.episode_id for episode in validation),
        provenance,
    )


def _tensors(episode: RhythmEpisode) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    """效用监督只形成标签，始终不会被编码进模型输入。"""
    features = torch.tensor([example.observation.features() for example in episode.examples], dtype=torch.float32)
    labels = torch.tensor([float(example.should_think) for example in episode.examples], dtype=torch.float32)
    seconds = torch.tensor([example.next_check_seconds for example in episode.examples], dtype=torch.float32)
    utility_weights = torch.tensor(
        [max(abs(example.think_value - example.wait_value), 0.001) for example in episode.examples], dtype=torch.float32
    )
    return features.unsqueeze(0), labels.unsqueeze(0), seconds.log1p().unsqueeze(0), utility_weights.unsqueeze(0)
