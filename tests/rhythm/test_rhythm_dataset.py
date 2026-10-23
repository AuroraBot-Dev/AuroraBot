"""验证节律观察、效用标注和时间分区的独立边界。"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from aurora_bot.cadence.state import observation_data
from aurora_bot.rhythm.dataset import read_episodes, validate_partition
from tests.rhythm.support import make_episode
from tests.support.training import _write

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def test_dataset_reads_explicit_utility_labels_and_rejects_temporal_leakage(tmp_path: Path) -> None:
    """日志输入和效用标签分别存储，验证经历不能穿插到训练历史中。"""
    episode = make_episode("train", False, _NOW)
    path = tmp_path / "dataset.jsonl"
    row = {
        "schema_version": 2,
        "episode_id": episode.episode_id,
        "examples": [
            {
                "observation": observation_data(example.observation),
                "think_value": example.think_value,
                "wait_value": example.wait_value,
                "next_check_seconds": example.next_check_seconds,
                "outcome_cursor": example.outcome_cursor,
                "outcome_at": example.outcome_at.isoformat(),
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


def test_partition_rejects_training_results_learned_after_validation_observation(tmp_path: Path) -> None:
    """训练观察较早不代表它的结果也较早，读取边界必须覆盖真实标签时间。"""
    path = tmp_path / "late-results.jsonl"
    _write(path, make_episode("training", True, _NOW))
    row = json.loads(path.read_text())
    for example in row["examples"]:
        example["outcome_cursor"] = example["observation"]["cursor"] + 100
        example["outcome_at"] = (_NOW + timedelta(days=2)).isoformat()
    path.write_text(json.dumps(row), encoding="utf-8")
    training = read_episodes(path)
    validation = (make_episode("validation", True, _NOW + timedelta(days=1)),)
    with pytest.raises(ValueError, match="训练结果"):
        validate_partition(training, validation)


@pytest.mark.parametrize("cursor_delta", [0, -1])
def test_outcome_must_follow_the_observation_cursor(cursor_delta: int) -> None:
    """观察之前已经存在的结果不能冒充本次等待或推理的后续效用。"""
    example = make_episode("training", True, _NOW).examples[0]
    with pytest.raises(ValueError, match="观察之后"):
        replace(example, outcome_cursor=example.observation.cursor + cursor_delta)


@pytest.mark.parametrize("at", [_NOW.replace(tzinfo=None), _NOW - timedelta(seconds=1)])
def test_outcome_time_is_aware_and_not_before_observation(at: datetime) -> None:
    """标签来源时间不能依赖本机时区，也不能早于推理机会。"""
    example = make_episode("training", True, _NOW).examples[0]
    with pytest.raises(ValueError, match=r"时间|观察之后"):
        replace(example, outcome_at=at)


def test_same_subject_validation_requires_a_later_world_prefix() -> None:
    """相同获知时间之外，独立世界游标也必须越过该主体的全部训练结果。"""
    training = make_episode("training", True, _NOW)
    validation = make_episode("validation", True, _NOW + timedelta(days=1))
    example = validation.examples[0]
    observation = replace(example.observation, bot_id=training.examples[0].observation.bot_id)
    validation = replace(validation, examples=(replace(example, observation=observation),))
    with pytest.raises(ValueError, match="训练结果游标"):
        validate_partition((training,), (validation,))
    last = max(item.outcome_cursor for item in training.examples)
    observation = replace(observation, cursor=last + 1)
    example = replace(example, observation=observation, outcome_cursor=last + 2)
    validate_partition((training,), (replace(validation, examples=(example,)),))


def test_training_format_requires_explicit_outcome_boundaries(tmp_path: Path) -> None:
    """不能为缺失的标签来源自动编造时间或把无边界数据当成当前格式。"""
    path = tmp_path / "dataset.jsonl"
    _write(path, make_episode("training", True, _NOW))
    row = json.loads(path.read_text())
    row["schema_version"] = 1
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version=2"):
        read_episodes(path)
    row["schema_version"] = 2
    del row["examples"][0]["outcome_at"]
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="outcome_at"):
        read_episodes(path)
