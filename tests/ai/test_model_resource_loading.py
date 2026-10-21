"""固定模型资源进入实际异步装配，不依赖训练时的导出路径。"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from importlib import import_module
from typing import TYPE_CHECKING

import pytest

from aurora_bot.artifacts.store import FileArtifactStore
from aurora_bot.contracts import TreeStatus
from aurora_bot.contracts.model_artifact import MODEL_MEDIA_TYPE
from aurora_bot.contracts.pkgs.artifacts import ArtifactStore
from aurora_bot.contracts.pkgs.cadence import RhythmPolicy
from aurora_bot.contracts.pkgs.memory import MemoryPolicy
from aurora_bot.contracts.pkgs.resources import ResourceCatalog
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.memory_model.config import MemoryModelConfig
from aurora_bot.memory_model.dataset import write_episodes
from aurora_bot.rhythm.config import RhythmConfig
from aurora_bot.runtime import compose_runtime
from aurora_cli.commander import run
from aurora_cli.commands import DEFAULT_REGISTRY
from tests.ai.learning_support import _config
from tests.memory.support import episodes
from tests.rhythm.support import make_episode
from tests.support.model import TemplateModel as FakeModel
from tests.support.training import _NOW, _write

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
def test_training_resource_loads_after_export_and_input_files_are_removed(
    configured_project: Path, capsys: pytest.CaptureFixture[str], domain: str
) -> None:
    """从实际训练命令获得的版本直接装配，原始路径不再参与模型加载。"""
    training, validation = configured_project / "training.jsonl", configured_project / "validation.jsonl"
    if domain == "rhythm":
        _write(training, make_episode("training", False, _NOW))
        _write(validation, make_episode("validation", False, _NOW + timedelta(days=1)))
    else:
        write_episodes(training, episodes("training"))
        write_episodes(validation, episodes("validation", days=1))
    assert (
        run(
            [
                "--root",
                str(configured_project),
                "train",
                domain,
                "training.jsonl",
                "validation.jsonl",
                "model.pt",
                "--epochs",
                "1",
            ],
            registry=DEFAULT_REGISTRY,
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    reference = ResourceRef(ResourceKey.parse(report["resource"]), report["revision"])
    (configured_project / "model.pt").unlink()
    training.unlink()
    validation.unlink()
    config = _config(configured_project, domain, ref=f"{reference.key}@{reference.revision}")

    async def scenario() -> None:
        runtime, handle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        stop = asyncio.Event()
        try:
            await handle.activate(stop)
            policy = runtime.assembly.get(MemoryPolicy) if domain == "memory" else runtime.assembly.get(RhythmPolicy)
            assert policy.ref == reference
            assert runtime.assembly.get(ResourceCatalog).resolve(reference).ref == reference
            assert (await runtime.assembly.get(ArtifactStore).stat(reference)).media_type == MODEL_MEDIA_TYPE
            result = await runtime.run("核对训练资源加载后的运行。")
            assert result.status is TreeStatus.COMPLETED
        finally:
            stop.set()
            await handle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
@pytest.mark.parametrize("media_type", [MODEL_MEDIA_TYPE, "application/octet-stream"])
def test_wrong_archive_or_media_type_is_not_used_as_model_weights(
    configured_project: Path, domain: str, media_type: str
) -> None:
    """存储摘要正确也不意味着内容可以解释为当前模型的张量权重。"""

    async def scenario() -> None:
        key = ResourceKey.parse(f"aurora:{domain}/model/{'tgn' if domain == 'memory' else 'gru'}")
        info = await FileArtifactStore(configured_project / "data/artifacts").put(
            key, b"broken bytes", media_type=media_type
        )
        config = _config(configured_project, domain, ref=f"{key}@{info.ref.revision}")
        with pytest.raises(ValueError, match=r"张量归档|媒体类型"):
            await compose_runtime(config, FakeModel(), output=lambda _: None)

    asyncio.run(scenario())


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
def test_path_weights_are_imported_before_runtime_construction(configured_project: Path, domain: str) -> None:
    """路径只在准备阶段读取一次，实际策略、资源目录和存储使用同一版本。"""
    backend = import_module(f"{'aurora_bot.rhythm' if domain == 'rhythm' else 'aurora_bot.memory_model'}.training")
    if domain == "rhythm":
        training = (make_episode("training", False, _NOW),)
        validation = (make_episode("validation", False, _NOW + timedelta(days=1)),)
    else:
        training, validation = episodes("training"), episodes("validation", days=1)
    result = backend.train(training, validation, epochs=1, hidden_size=4)
    reference = result.save(configured_project / "path-model.pt")
    assert not (configured_project / "data/artifacts").exists()
    config = _config(configured_project, domain, weights="path-model.pt")

    async def scenario() -> None:
        runtime, handle = await compose_runtime(config, FakeModel(), output=lambda _: None)
        try:
            policy = runtime.assembly.get(MemoryPolicy) if domain == "memory" else runtime.assembly.get(RhythmPolicy)
            assert policy.ref == reference
            assert (await runtime.assembly.get(ArtifactStore).stat(reference)).media_type == MODEL_MEDIA_TYPE
            (configured_project / "path-model.pt").unlink()
            assert runtime.assembly.get(ResourceCatalog).resolve(reference).ref == reference
        finally:
            await handle.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
def test_unknown_resource_version_does_not_fall_back_to_another_model(configured_project: Path, domain: str) -> None:
    """指定版本不可用时必须启动失败，不能静默改用规则或其他权重。"""
    key = f"aurora:{domain}/model/{'tgn' if domain == 'memory' else 'gru'}"
    config = _config(configured_project, domain, ref=f"{key}@{'a' * 64}")

    async def scenario() -> None:
        with pytest.raises(LookupError, match="资源版本不存在"):
            await compose_runtime(config, FakeModel(), output=lambda _: None)

    asyncio.run(scenario())


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
def test_resource_version_is_required_and_path_cannot_be_mixed_in(domain: str) -> None:
    """引用不能使用隐式最新版本，也不能悄悄退回另一个路径来源。"""
    config_type = MemoryModelConfig if domain == "memory" else RhythmConfig
    key = f"aurora:{domain}/model/{'tgn' if domain == 'memory' else 'gru'}"
    with pytest.raises(ValueError, match="SHA256"):
        config_type(policy=key, weights_ref=key)
    with pytest.raises(ValueError, match="只能选择一项"):
        config_type(policy=key, weights="model.pt", weights_ref=f"{key}@{'a' * 64}")
    with pytest.raises(ValueError, match="配置所选的模型"):
        config_type(policy=key, weights_ref=f"lab:{domain}/model/other@{'a' * 64}")
