"""模型来源绑定实际训练样本，标签变化不能被相同经历身份掩盖。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from importlib import import_module
from io import BytesIO

import pytest
import torch

from aurorabot.contracts.training import TrainingProvenance, provenance_data
from aurorabot.rhythm.dataset import episodes_fingerprint
from tests.memory_support import episodes
from tests.rhythm_support import make_episode

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
def test_actual_dataset_fingerprints_are_saved_inside_model_bytes(domain: str) -> None:
    """直接调用训练器也产生输入内容身份，未发布的原始来源保持空值。"""
    package = "aurorabot.rhythm" if domain == "rhythm" else "aurorabot.memory_model"
    dataset = import_module(f"{package}.dataset")
    trainer = import_module(f"{package}.training")
    if domain == "rhythm":
        training = (make_episode("training", False, _NOW),)
        validation = (make_episode("validation", False, _NOW + timedelta(days=1)),)
    else:
        training = episodes("training")
        validation = episodes("validation", days=1)
    result = trainer.train(training, validation, epochs=1, hidden_size=4)
    expected = TrainingProvenance(
        domain, dataset.episodes_fingerprint(training), dataset.episodes_fingerprint(validation)
    )
    assert result.provenance == expected
    model = torch.load(BytesIO(result.to_bytes()), weights_only=True)
    assert model["training"]["data"] == provenance_data(expected)
    assert model["training"]["data"]["training"]["source"] is None
    assert model["training"]["data"]["validation"]["source"] is None


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
def test_changed_labels_with_the_same_episode_ids_reject_original_source_declaration(
    domain: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """在任何参数初始化和优化之前，声明必须与当前输入摘要相符。"""
    package = "aurorabot.rhythm" if domain == "rhythm" else "aurorabot.memory_model"
    dataset = import_module(f"{package}.dataset")
    trainer = import_module(f"{package}.training")
    if domain == "rhythm":
        training = (make_episode("training", False, _NOW),)
        validation = (make_episode("validation", False, _NOW + timedelta(days=1)),)
        first = replace(training[0].examples[0], think_value=training[0].examples[0].think_value + 1)
    else:
        training = episodes("training")
        validation = episodes("validation", days=1)
        example = training[0].examples[0]
        first = replace(example, utilities=(example.utilities[0] + 1, *example.utilities[1:]))
    declared = TrainingProvenance(
        domain, dataset.episodes_fingerprint(training), dataset.episodes_fingerprint(validation)
    )
    altered = (replace(training[0], examples=(first, *training[0].examples[1:])), *training[1:])
    assert dataset.episodes_fingerprint(altered) != declared.training_digest

    def unavailable(*args: object, **kwargs: object) -> None:
        """来源已失配，不应开始任何网络初始化。"""
        raise AssertionError("不应初始化模型")

    network_name = "RhythmNetwork" if domain == "rhythm" else "TemporalMemoryNetwork"
    monkeypatch.setattr(trainer, network_name, unavailable)
    with pytest.raises(ValueError, match="实际训练输入不一致"):
        trainer.train(altered, validation, epochs=1, provenance=declared)


def test_fingerprint_normalizes_timezone_representation_but_preserves_order() -> None:
    """同一观察时刻的时区表示等价，样本本身的顺序仍参与摘要。"""
    episode = make_episode("training", False, _NOW)
    zone = timezone(timedelta(hours=8))
    shifted = replace(
        episode,
        examples=tuple(
            replace(
                example,
                observation=replace(example.observation, observed_at=example.observation.observed_at.astimezone(zone)),
            )
            for example in episode.examples
        ),
    )
    assert episodes_fingerprint((shifted,)) == episodes_fingerprint((episode,))
    other = replace(episode, episode_id="other")
    assert episodes_fingerprint((episode, other)) != episodes_fingerprint((other, episode))
