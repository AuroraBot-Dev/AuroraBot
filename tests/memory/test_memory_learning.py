"""真实训练验证图历史的独立作用，导出与重载共用在线评分。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Any

import pytest
import torch

from aurora_bot.memory_model.dataset import read_episodes, validate_partition, write_episodes
from aurora_bot.memory_model.tgn import TGNMemoryPolicy, load_policy
from aurora_bot.memory_model.training import train
from tests.memory.support import episodes

if TYPE_CHECKING:
    from io import BytesIO
    from pathlib import Path

    from aurora_bot.memory_model.training import MemoryTrainingResult


@pytest.fixture(scope="module")
def learned() -> MemoryTrainingResult:
    """一次受控训练供独立的机制验证共享，测试不重复优化模型。"""
    return train(
        episodes("train"),
        episodes("validation", days=1),
        hidden_size=8,
        text_dimensions=16,
        epochs=50,
        learning_rate=0.02,
        seed=7,
    )


def test_training_uses_graph_history_and_roundtrip_preserves_scores(
    tmp_path: Path, learned: MemoryTrainingResult
) -> None:
    """独立较晚经历上的图模型能区分基线无法区分的当前候选。"""
    validation = episodes("validation", days=1)
    result = learned
    assert result.losses[-1] < result.losses[0]
    assert result.metrics["top1_accuracy"] > result.baseline_metrics["top1_accuracy"]
    assert result.metrics["regret"] < result.baseline_metrics["regret"]
    path = tmp_path / "tgn.pt"
    ref = result.save(path)
    restored = load_policy(path)
    original = TGNMemoryPolicy(result.network, "before-save")
    assert restored.ref == ref
    for episode in validation:
        request = episode.examples[0].request
        assert restored.score(request) == original.score(request)


def test_dataset_keeps_outcome_separate_and_rejects_future_training_labels(tmp_path: Path) -> None:
    """JSONL 完整保留读取前缀，训练结果晚于验证查询时不能导出模型。"""
    training, validation = episodes("train"), episodes("validation", days=1)
    path = tmp_path / "memory.jsonl"
    write_episodes(path, training)
    assert read_episodes(path) == training
    validate_partition(training, validation)
    example = training[0].examples[0]
    with pytest.raises(ValueError, match="推荐之后"):
        replace(example, outcome_cursor=example.request.cursor)
    late = replace(example, outcome_at=validation[0].examples[0].request.observed_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="晚于所有训练结果"):
        validate_partition((replace(training[0], examples=(late,)),), validation)
    with pytest.raises(ValueError, match="不能重复"):
        validate_partition(training, training)


def test_model_revision_comes_from_the_same_bytes_as_loaded_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, learned: MemoryTrainingResult
) -> None:
    """其他进程在加载期间替换文件时，版本仍描述实际加载的内容。"""
    path = tmp_path / "memory.pt"
    learned.save(path)
    content = path.read_bytes()
    original_load = torch.load

    def load_then_replace(source: BytesIO, *, map_location: str, weights_only: bool) -> dict[str, Any]:
        """在张量读取结束之后模拟文件被外部替换。"""
        data = original_load(source, map_location=map_location, weights_only=weights_only)
        path.write_bytes(b"a later artifact")
        return data

    monkeypatch.setattr(torch, "load", load_then_replace)
    policy = load_policy(path)
    assert policy.ref.revision == sha256(content).hexdigest()
    request = episodes("check")[0].examples[0].request
    assert policy.score(request) == TGNMemoryPolicy(learned.network, "original").score(request)


def test_incompatible_coordinates_and_nonfinite_weights_are_rejected(
    tmp_path: Path, learned: MemoryTrainingResult
) -> None:
    """关系词表变化或损坏的张量不能静默成为新的推荐策略。"""
    path = tmp_path / "memory.pt"
    learned.save(path)
    data = torch.load(path, weights_only=True)
    data["relations"].reverse()
    torch.save(data, path)
    with pytest.raises(ValueError, match="关系坐标"):
        load_policy(path)
    learned.save(path)
    data = torch.load(path, weights_only=True)
    first = next(iter(data["state_dict"].values()))
    first.fill_(float("nan"))
    torch.save(data, path)
    with pytest.raises(ValueError, match="非有限"):
        load_policy(path)
