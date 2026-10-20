"""训练产物绑定实际读取的数据资源，输出文件只是同一模型的导出。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import timedelta
from importlib import import_module
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
import torch

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurorabot.artifacts.store import FileArtifactStore
from aurorabot.contracts.artifact_codec import read_artifact
from aurorabot.contracts.artifact_io import artifact_content
from aurorabot.contracts.resource_query import ResourceQuery
from aurorabot.memory_model.dataset import write_episodes
from aurorabot.utils.files import write_new_file
from tests.memory_support import episodes
from tests.rhythm_support import make_episode
from tests.test_train_command import _NOW, _write

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("domain", ["rhythm", "memory"])
def test_cli_publishes_the_exact_inputs_and_model_with_portable_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, domain: str
) -> None:
    """在优化开始时修改源文件，归档仍必须指向之前实际解析的同一份字节。"""
    training_path = tmp_path / "training.jsonl"
    validation_path = tmp_path / "validation.jsonl"
    if domain == "rhythm":
        _write(training_path, make_episode("training", False, _NOW))
        _write(validation_path, make_episode("validation", False, _NOW + timedelta(days=1)))
    else:
        write_episodes(training_path, episodes("training"))
        write_episodes(validation_path, episodes("validation", days=1))
    original_training = training_path.read_bytes()
    original_validation = validation_path.read_bytes()
    package = "aurorabot.rhythm" if domain == "rhythm" else "aurorabot.memory_model"
    backend = import_module(f"{package}.training")
    dataset = import_module(f"{package}.dataset")
    actual_train = backend.train

    def train(training: tuple[object, ...], validation: tuple[object, ...], **kwargs: object) -> object:
        """文件变化发生在快照固定之后，仍使用真实训练算法。"""
        training_path.write_bytes(b"changed after capture")
        validation_path.unlink()
        return actual_train(training, validation, **kwargs)

    monkeypatch.setattr(backend, "train", train)
    code = run(
        ["--root", str(tmp_path), "train", domain, "training.jsonl", "validation.jsonl", "model.pt", "--epochs", "1"],
        registry=DEFAULT_REGISTRY,
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    model_info = read_artifact(report["artifact"])
    model_content = (tmp_path / "model.pt").read_bytes()
    assert model_info.ref.revision == hashlib.sha256(model_content).hexdigest() == report["revision"]
    metadata = torch.load(BytesIO(model_content), weights_only=True)
    assert metadata["training"]["data"] == report["inputs"]

    async def scenario() -> None:
        store = FileArtifactStore(tmp_path / "data/artifacts")
        published = await store.find(ResourceQuery(domain=domain))
        assert model_info in published.items
        assert await artifact_content(store, model_info) == model_content
        for role, original in (("training", original_training), ("validation", original_validation)):
            source = read_artifact(report["inputs"][role]["source"])
            assert source in published.items
            assert await artifact_content(store, source) == original
            assert source.ref.revision == hashlib.sha256(original).hexdigest()
            assert report["inputs"][role]["input_digest"] == dataset.episodes_fingerprint(
                dataset.parse_episodes(original)
            )

    asyncio.run(scenario())


def test_training_uses_the_artifact_directory_from_its_own_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """训练不要求其他运行配置，但必须与 Bot 共用同一内容存储位置。"""
    config = tmp_path / "config"
    config.mkdir()
    (config / "artifacts.toml").write_text('[artifacts]\ndirectory = "resources/content"\n', encoding="utf-8")
    _write(tmp_path / "training.jsonl", make_episode("training", False, _NOW))
    _write(tmp_path / "validation.jsonl", make_episode("validation", False, _NOW + timedelta(days=1)))
    assert (
        run(
            [
                "--root",
                str(tmp_path),
                "train",
                "rhythm",
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

    async def scenario() -> None:
        model = read_artifact(report["artifact"])
        assert await FileArtifactStore(tmp_path / "resources/content").stat(model.ref) == model

    asyncio.run(scenario())
    assert not (tmp_path / "data/artifacts").exists()


def test_new_file_publication_keeps_existing_output_and_cleans_temporary_content(tmp_path: Path) -> None:
    """文件发布原子且不覆盖，失败后目录中没有半份新文件。"""
    path = tmp_path / "model.pt"
    write_new_file(path, b"first model")
    with pytest.raises(FileExistsError, match="已经存在"):
        write_new_file(path, b"different model")
    assert path.read_bytes() == b"first model"
    assert tuple(tmp_path.iterdir()) == (path,)
