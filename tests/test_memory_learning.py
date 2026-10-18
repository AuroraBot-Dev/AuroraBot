"""真实训练验证图历史的独立作用，导出与重载共用在线评分。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from memory_support import episodes

from src.memory_model.dataset import read_episodes, validate_partition, write_episodes
from src.memory_model.tgn import TGNMemoryPolicy, load_policy
from src.memory_model.training import train

if TYPE_CHECKING:
    from pathlib import Path


def test_training_uses_graph_history_and_roundtrip_preserves_scores(tmp_path: Path) -> None:
    """独立较晚经历上的图模型能区分基线无法区分的当前候选。"""
    training, validation = episodes("train"), episodes("validation", days=1)
    result = train(training, validation, hidden_size=8, text_dimensions=16, epochs=50, learning_rate=0.02, seed=7)
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
