"""验证节律观察、效用标注和时间分区的独立边界。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from rhythm_support import make_episode

from src.cadence.state import observation_data
from src.rhythm.dataset import read_episodes, validate_partition

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def test_dataset_reads_explicit_utility_labels_and_rejects_temporal_leakage(tmp_path: Path) -> None:
    """日志输入和效用标签分别存储，验证经历不能穿插到训练历史中。"""
    episode = make_episode("train", False, _NOW)
    path = tmp_path / "dataset.jsonl"
    row = {
        "schema_version": 1,
        "episode_id": episode.episode_id,
        "examples": [
            {
                "observation": observation_data(example.observation),
                "think_value": example.think_value,
                "wait_value": example.wait_value,
                "next_check_seconds": example.next_check_seconds,
            }
            for example in episode.examples
        ],
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    assert read_episodes(path) == (episode,)
    with pytest.raises(ValueError, match="同一经历"):
        validate_partition((episode,), (episode,))
    with pytest.raises(ValueError, match="晚于"):
        validate_partition((episode,), (make_episode("validation", True, _NOW),))
