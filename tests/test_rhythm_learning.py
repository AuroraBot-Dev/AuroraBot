"""真实训练、循环推理、独立验证与权重恢复的离线测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import torch

from aurora import load_config
from aurora.configs.rhythm import CONFIG_SPEC as RHYTHM_CONFIG
from aurorabot.contracts import EnvironmentEvent
from aurorabot.contracts.pkgs.cadence import Cadence, RhythmPolicy
from aurorabot.rhythm.config import RhythmConfig
from aurorabot.rhythm.dataset import RhythmEpisode
from aurorabot.rhythm.gru import GRURhythmPolicy, load_policy
from aurorabot.rhythm.training import RhythmTrainingResult, train
from aurorabot.runtime import assemble_runtime
from tests.model_support import TemplateModel as FakeModel
from tests.rhythm_support import make_episode

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
_HIDDEN_SIZE = 8
_MIN_PROBABILITY_GAP = 0.5


@pytest.fixture(scope="module", autouse=True)
def single_thread_cpu() -> Iterator[None]:
    """在模块测试期间使用单线程 CPU，完成后恢复进程配置。"""
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous_threads)


@pytest.fixture(scope="module")
def learned() -> RhythmTrainingResult:
    """使用小型确定样本训练真实 GRU。"""
    training = (make_episode("train-low", False, _NOW), make_episode("train-high", True, _NOW))
    later = _NOW + timedelta(days=1)
    validation = (make_episode("valid-low", False, later), make_episode("valid-high", True, later))
    return train(training, validation, hidden_size=_HIDDEN_SIZE, epochs=120, learning_rate=0.03)


def test_training_reduces_loss_and_uses_history_to_improve_over_rule_baseline(learned: RhythmTrainingResult) -> None:
    """模型需要利用先前经历，单靠当前特征无法区分两种标签。"""
    assert learned.losses[-1] < learned.losses[0] / 3
    assert learned.metrics["regret"] < learned.baseline_metrics["regret"]
    policy = GRURhythmPolicy(learned.network, "test")
    low = make_episode("low", False, _NOW).examples
    high = make_episode("high", True, _NOW).examples
    low_state = policy.evaluate(low[0].observation).hidden
    high_state = policy.evaluate(high[0].observation).hidden
    assert low[1].observation.features() == high[1].observation.features()
    low_next = policy.evaluate(low[1].observation, low_state)
    high_next = policy.evaluate(high[1].observation, high_state)
    assert high_next.decision.probability - low_next.decision.probability > _MIN_PROBABILITY_GAP


def test_weight_export_and_reload_preserve_online_predictions(tmp_path: Path, learned: RhythmTrainingResult) -> None:
    """权重重载后逐步输出和循环状态保持一致，版本由内容确定。"""
    path = tmp_path / "rhythm.pt"
    learned.save(path)
    restored = load_policy(path)
    original = GRURhythmPolicy(learned.network, "original")
    observation = make_episode("test", True, _NOW).examples[0].observation
    assert restored.evaluate(observation) == original.evaluate(observation)
    assert restored.ref.revision == load_policy(path).ref.revision
    with pytest.raises(ValueError, match="维度"):
        restored.evaluate(observation, (1.0,))


def test_incompatible_feature_coordinates_are_not_loaded(tmp_path: Path, learned: RhythmTrainingResult) -> None:
    """输入坐标改变后拒绝复用权重，避免静默错误推理。"""
    path = tmp_path / "rhythm.pt"
    learned.save(path)
    data = torch.load(path, weights_only=True)
    data["features"] = list(reversed(data["features"]))
    torch.save(data, path)
    with pytest.raises(ValueError, match="特征"):
        load_policy(path)


def test_training_accounts_for_utility_magnitude_not_only_label_counts() -> None:
    """相同观察下两类标签各半，较大的延误损失应改变最优选择。"""
    example = make_episode("base", False, _NOW).examples[0]
    later = make_episode("later", False, _NOW + timedelta(days=1)).examples[0]
    training = (
        RhythmEpisode("valuable", (replace(example, think_value=20, wait_value=0),)),
        RhythmEpisode("costly", (replace(example, think_value=0, wait_value=1),)),
    )
    validation = (
        RhythmEpisode("valid-valuable", (replace(later, think_value=20, wait_value=0),)),
        RhythmEpisode("valid-costly", (replace(later, think_value=0, wait_value=1),)),
    )
    result = train(training, validation, hidden_size=_HIDDEN_SIZE, epochs=80, learning_rate=0.03)
    assert result.metrics["regret"] < result.baseline_metrics["regret"]
    assert result.losses[-1] < result.losses[0]


def test_configured_bot_uses_real_weights_and_persists_gru_state(
    configured_project: Path, learned: RhythmTrainingResult
) -> None:
    """实际组合选择导出的模型，世界日志记录同一版本与循环状态。"""
    path = configured_project / "rhythm.pt"
    learned.save(path)
    config = load_config(configured_project).with_value(
        RHYTHM_CONFIG, RhythmConfig(policy="aurora:rhythm/model/gru", weights="rhythm.pt")
    )
    runtime = assemble_runtime(config, FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        try:
            policy = runtime.assembly.get(RhythmPolicy)
            assert policy.ref == load_policy(path).ref
            await runtime.submit_event(EnvironmentEvent("first", "test", "test:world", "message", _NOW, "变化"))
            cadence = runtime.assembly.get(Cadence)
            await cadence.evaluate_once()
            records = await runtime.world.commits("aurora:world/bot/default/cadence", 0, 20)
            decisions = [record for record in records if "decision" in record.data]
            assert decisions[-1].data["policy"]["revision"] == policy.ref.revision
            assert len(decisions[-1].data["state"]["hidden"]) == _HIDDEN_SIZE
            assert decisions[-1].data["policy_parameters"] == dict(policy.parameters)
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
