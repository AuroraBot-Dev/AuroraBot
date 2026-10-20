"""具有显式循环状态和独立检查时长输出的 GRU 节律模型。"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import timedelta
from typing import TYPE_CHECKING

import torch
from torch import Tensor, nn

from aurorabot.contracts.model_artifact import model_archive, model_content_ref
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.contracts.rhythm import RHYTHM_FEATURES, RhythmAction, RhythmDecision, RhythmPrediction

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.contracts.rhythm import RhythmObservation

GRU_KEY = ResourceKey.parse("aurora:rhythm/model/gru")


class RhythmNetwork(nn.Module):
    """循环编码后分别估计思考价值和下次检查时长。"""

    def __init__(self, hidden_size: int = 16) -> None:
        """固定输入坐标，隐层大小写入权重元数据。"""
        super().__init__()
        if hidden_size <= 0:
            raise ValueError("节律隐层大小必须大于零")
        self.hidden_size = hidden_size
        self.recurrent = nn.GRU(len(RHYTHM_FEATURES), hidden_size, batch_first=True)
        self.wake_head = nn.Linear(hidden_size, 1)
        self.delay_head = nn.Linear(hidden_size, 1)

    def forward(self, features: Tensor, hidden: Tensor | None = None) -> tuple[Tensor, Tensor, Tensor]:
        """序列训练和单步在线推理使用相同计算图。"""
        encoded, updated = self.recurrent(features, hidden)
        wake_logits = self.wake_head(encoded).squeeze(-1)
        log_delay = nn.functional.softplus(self.delay_head(encoded).squeeze(-1))
        return wake_logits, log_delay, updated


class GRURhythmPolicy:
    """权重不可变，Bot 的隐状态由调用者显式传入并保存。"""

    def __init__(
        self,
        network: RhythmNetwork,
        revision: str,
        *,
        min_check_seconds: float = 1,
        max_check_seconds: float = 3600,
        probability_threshold: float = 0.5,
    ) -> None:
        """时间范围由环境表达，模型在该范围内安排下一次检查。"""
        if not 0 < min_check_seconds <= max_check_seconds or not 0 < probability_threshold < 1:
            raise ValueError("节律检查间隔或概率阈值无效")
        self._network = deepcopy(network).cpu().eval().requires_grad_(False)
        self._ref = ResourceRef(GRU_KEY, revision)
        self.min_check_seconds = min_check_seconds
        self.max_check_seconds = max_check_seconds
        self.probability_threshold = probability_threshold

    @property
    def ref(self) -> ResourceRef:
        """资源版本由实际权重内容决定。"""
        return self._ref

    @property
    def parameters(self) -> dict[str, float | int]:
        """阈值和时间界限与权重身份分别记录。"""
        return {
            "min_check_seconds": self.min_check_seconds,
            "max_check_seconds": self.max_check_seconds,
            "probability_threshold": self.probability_threshold,
        }

    def evaluate(self, observation: RhythmObservation, hidden: tuple[float, ...] = ()) -> RhythmPrediction:
        """只使用已声明的观察特征，输出可直接持久化的状态。"""
        if hidden and len(hidden) != self._network.hidden_size:
            raise ValueError("节律隐状态与模型维度不匹配")
        if any(not math.isfinite(value) for value in hidden):
            raise ValueError("节律隐状态包含非有限数值")
        features = torch.tensor(observation.features(), dtype=torch.float32).reshape(1, 1, -1)
        previous = torch.tensor(hidden, dtype=torch.float32).reshape(1, 1, -1) if hidden else None
        with torch.no_grad():
            logits, log_delay, updated = self._network(features, previous)
        probability = float(logits.sigmoid().item())
        seconds = math.expm1(min(float(log_delay.item()), math.log1p(self.max_check_seconds)))
        seconds = min(self.max_check_seconds, max(self.min_check_seconds, seconds))
        action = RhythmAction.DELIBERATE if probability >= self.probability_threshold else RhythmAction.WAIT
        decision = RhythmDecision(
            action,
            observation.observed_at + timedelta(seconds=seconds),
            "节律模型分配推理机会" if action is RhythmAction.DELIBERATE else "节律模型选择继续等待",
            observation.active_goal_ids,
            probability,
        )
        return RhythmPrediction(decision, tuple(updated.flatten().tolist()))


def load_policy(
    path: Path,
    *,
    min_check_seconds: float = 1,
    max_check_seconds: float = 3600,
    probability_threshold: float = 0.5,
) -> GRURhythmPolicy:
    """只加载张量与基础元数据，输入坐标变化时拒绝混用权重。"""
    return load_policy_bytes(
        path.read_bytes(),
        min_check_seconds=min_check_seconds,
        max_check_seconds=max_check_seconds,
        probability_threshold=probability_threshold,
    )


def load_policy_bytes(
    content: bytes,
    *,
    expected: ResourceRef | None = None,
    min_check_seconds: float = 1,
    max_check_seconds: float = 3600,
    probability_threshold: float = 0.5,
) -> GRURhythmPolicy:
    """按实际字节固定版本，可在张量解码前核对资源引用。"""
    ref = model_content_ref(content, GRU_KEY, expected)
    assert ref.revision is not None
    data = torch.load(model_archive(content), map_location="cpu", weights_only=True)
    if data["schema_version"] != 1 or data["model_key"] != str(GRU_KEY):
        raise ValueError("不支持的节律权重格式")
    if tuple(data["features"]) != RHYTHM_FEATURES:
        raise ValueError("节律权重的输入特征不兼容")
    network = RhythmNetwork(data["hidden_size"])
    network.load_state_dict(data["state_dict"], strict=True)
    if any(not bool(torch.isfinite(parameter).all()) for parameter in network.parameters()):
        raise ValueError("节律权重包含非有限数值")
    return GRURhythmPolicy(
        network,
        ref.revision,
        min_check_seconds=min_check_seconds,
        max_check_seconds=max_check_seconds,
        probability_threshold=probability_threshold,
    )
