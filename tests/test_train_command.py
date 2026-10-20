"""验证训练命令的真实数据读取、验证与权重导出。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurorabot.memory_model.dataset import write_episodes
from aurorabot.memory_model.tgn import load_policy as load_memory_policy
from aurorabot.rhythm.dataset import write_episodes as write_rhythm_episodes
from aurorabot.rhythm.gru import load_policy
from tests.memory_support import episodes
from tests.rhythm_support import make_episode

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from aurorabot.rhythm.dataset import RhythmEpisode

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _write(path: Path, episode: RhythmEpisode) -> None:
    """按公开 JSONL 结构写入测试经历，不调用网络。"""
    write_rhythm_episodes(path, (episode,))


def test_train_command_exports_reloadable_weights_and_independent_validation_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI 使用实际训练器，报告与权重均可读取。"""
    _write(tmp_path / "train.jsonl", make_episode("train", False, _NOW))
    _write(tmp_path / "validation.jsonl", make_episode("valid", False, _NOW + timedelta(days=1)))
    arguments = [
        "--root",
        str(tmp_path),
        "train",
        "rhythm",
        "train.jsonl",
        "validation.jsonl",
        "rhythm.pt",
        "--epochs",
        "2",
        "--hidden-size",
        "4",
    ]
    assert run(arguments, registry=DEFAULT_REGISTRY) == 0
    report = json.loads(capsys.readouterr().out)
    assert "validation" in report and "baseline" in report
    assert load_policy(tmp_path / "rhythm.pt").ref.revision == report["revision"]
    assert run(arguments, registry=DEFAULT_REGISTRY) != 0
    assert "已经存在" in capsys.readouterr().err


def test_train_command_rejects_validation_leakage_before_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """相同经历不能同时用于训练与验证，也不生成权重文件。"""
    _write(tmp_path / "same.jsonl", make_episode("same", False, _NOW))
    arguments = ["--root", str(tmp_path), "train", "rhythm", "same.jsonl", "same.jsonl", "rhythm.pt"]
    assert run(arguments, registry=DEFAULT_REGISTRY) != 0
    assert "同一经历" in capsys.readouterr().err
    assert not (tmp_path / "rhythm.pt").exists()


def test_memory_train_command_exports_real_graph_weights_and_baseline_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """同一训练入口选择记忆数据格式，并实际导出时序图模型。"""
    write_episodes(tmp_path / "train.jsonl", episodes("train"))
    write_episodes(tmp_path / "validation.jsonl", episodes("validation", days=1))
    arguments = [
        "--root",
        str(tmp_path),
        "train",
        "memory",
        "train.jsonl",
        "validation.jsonl",
        "memory.pt",
        "--epochs",
        "2",
        "--hidden-size",
        "4",
    ]
    assert run(arguments, registry=DEFAULT_REGISTRY) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["resource"] == "aurora:memory/model/tgn"
    assert "top1_accuracy" in report["validation"]
    assert "regret" in report["baseline"]
    assert load_memory_policy(tmp_path / "memory.pt").ref.revision == report["revision"]
    assert run(arguments, registry=DEFAULT_REGISTRY) != 0
    assert "已经存在" in capsys.readouterr().err
