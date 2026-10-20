"""模型与数据通过不可变字节传递，路径变化不能混淆实际内容版本。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import TYPE_CHECKING

import pytest
import torch

from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.memory_model.dataset import write_episodes
from aurorabot.rhythm.gru import GRURhythmPolicy
from aurorabot.rhythm.training import train as train_rhythm
from tests.memory.support import episodes
from tests.rhythm.support import make_episode

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.mark.parametrize("package", ["aurorabot.rhythm", "aurorabot.memory_model"])
def test_model_export_bytes_are_independent_of_output_path(package: str, tmp_path: Path) -> None:
    """一次归档可同时保存到不同位置，加载与保存报告使用同一内容摘要。"""
    trainer = import_module(f"{package}.training")
    model = import_module(f"{package}.{'gru' if package == 'aurorabot.rhythm' else 'tgn'}")
    if package == "aurorabot.rhythm":
        training = (make_episode("training", False, _NOW),)
        validation = (make_episode("validation", False, _NOW + timedelta(days=1)),)
    else:
        training = episodes("training")
        validation = episodes("validation", days=1)
    result = trainer.train(training, validation, epochs=1, hidden_size=4)
    content = result.to_bytes()
    first = result.save(tmp_path / "first.pt")
    second = result.save(tmp_path / "second.pt")
    assert (tmp_path / "first.pt").read_bytes() == content == (tmp_path / "second.pt").read_bytes()
    assert first == second == model.load_policy_bytes(content, expected=first).ref


@pytest.mark.parametrize("package", ["aurorabot.rhythm", "aurorabot.memory_model"])
def test_model_version_is_checked_before_tensor_decoding(package: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """错误版本或错误模型身份不能先把字节交给计算框架加载。"""
    model = import_module(f"{package}.{'gru' if package == 'aurorabot.rhythm' else 'tgn'}")
    key = model.GRU_KEY if package == "aurorabot.rhythm" else model.TGN_KEY

    def unavailable(*args: object, **kwargs: object) -> None:
        """版本校验失败时不应访问张量解析器。"""
        raise AssertionError("不应解码错误版本")

    monkeypatch.setattr(torch, "load", unavailable)
    for expected in (
        ResourceRef(key, "a" * 64),
        ResourceRef(ResourceKey("lab", key.domain, "model", "other"), "b" * 64),
    ):
        with pytest.raises(ValueError, match="指定资源版本"):
            model.load_policy_bytes(b"different content", expected=expected)


def test_dataset_parsing_uses_captured_bytes_after_original_file_changes(tmp_path: Path) -> None:
    """训练快照来自捕获的字节，原文件变化不会改变已解析样本。"""
    dataset = import_module("aurorabot.memory_model.dataset")
    path = tmp_path / "memory.jsonl"
    original = episodes("training")
    write_episodes(path, original)
    content = path.read_bytes()
    path.write_bytes(b"now invalid")
    assert dataset.parse_episodes(content) == original
    with pytest.raises(ValueError):
        dataset.read_episodes(path)


def test_online_gru_owns_fixed_weights_separate_from_the_training_network() -> None:
    """继续修改训练结果不能暗中改变已登记版本的在线预测。"""
    training = (make_episode("training", False, _NOW),)
    validation = (make_episode("validation", False, _NOW + timedelta(days=1)),)
    result = train_rhythm(training, validation, epochs=1, hidden_size=4)
    policy = GRURhythmPolicy(result.network, "fixed")
    observation = training[0].examples[0].observation
    expected = policy.evaluate(observation)
    with torch.no_grad():
        for parameter in result.network.parameters():
            parameter.add_(1.0)
    assert policy.evaluate(observation) == expected
