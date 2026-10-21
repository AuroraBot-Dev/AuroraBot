"""提供训练命令插件，验证 Bot 的节律和记忆策略并导出明确版本的模型权重。"""

from __future__ import annotations

import asyncio
import json
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from aurora_bot.artifacts.config import ArtifactsConfig
from aurora_bot.artifacts.store import FileArtifactStore
from aurora_bot.contracts.artifact_codec import artifact_data
from aurora_bot.contracts.artifact_io import artifact_content
from aurora_bot.contracts.model_artifact import MODEL_MEDIA_TYPE
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.contracts.training import TrainingProvenance, provenance_data
from aurora_bot.utils.files import write_new_file
from aurora_cli.plugins import command_plugin
from aurora_cli.utils.process import EXIT_FAILURE

if TYPE_CHECKING:
    import argparse
    from types import ModuleType
    from typing import Any

    from aurora_bot.contracts.artifact import ArtifactInfo
    from aurora_bot.contracts.pkgs.artifacts import ArtifactStore
    from aurora_cli.contracts.command import CommandSpec, SubcommandSpec


def _training_spec(description: str) -> SubcommandSpec:
    """两个策略共用输入、时序验证和训练参数约定。"""
    return {
        "help": description,
        "args": {
            "training": {"type": Path, "help": "带效用标注的训练 JSONL"},
            "validation": {"type": Path, "help": "较晚且独立的验证 JSONL"},
            "output": {"type": Path, "help": "要导出的权重文件"},
        },
        "options": {
            "--epochs": {"type": int, "default": 100, "help": "训练轮数"},
            "--hidden-size": {"type": int, "default": 16, "help": "模型隐层大小"},
            "--learning-rate": {"type": float, "default": 0.01, "help": "优化器学习率"},
            "--seed": {"type": int, "default": 0, "help": "确定训练随机种子"},
        },
    }


COMMAND: CommandSpec = {
    "name": "train",
    "help": "训练和验证 Bot 的轻量策略",
    "subcommands": {
        "rhythm": _training_spec("按连续经历训练 GRU 节律模型，并与规则策略比较"),
        "memory": _training_spec("按后续效用训练时序图记忆模型，并与规则策略比较"),
    },
}


def execute(arguments: argparse.Namespace) -> int:
    """校验独立时间分区，训练后导出报告，不自动替换 Bot 正在使用的模型。"""
    try:
        package = {"rhythm": "aurora_bot.rhythm", "memory": "aurora_bot.memory_model"}[arguments.subcommand]
        dataset = import_module(f"{package}.dataset")
        backend = import_module(f"{package}.training")
    except ModuleNotFoundError as error:
        if error.name not in {"torch", "numpy"}:
            raise
        sys.stderr.write("训练依赖未安装，请运行 uv sync --extra learning。\n")
        return EXIT_FAILURE
    try:
        output = arguments.root / arguments.output
        if output.exists():
            raise ValueError("输出权重已经存在，请为这次训练指定新的文件")
        report = asyncio.run(_train(arguments, dataset, backend, output))
    except (ValueError, OSError) as error:
        sys.stderr.write(f"模型训练失败：{error}\n")
        return EXIT_FAILURE
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 0


async def _train(
    arguments: argparse.Namespace, dataset: ModuleType, backend: ModuleType, output: Path
) -> dict[str, Any]:
    """解析与训练均使用已发布的数据快照，不在完成训练后重新打开输入文件。"""
    root = arguments.root
    catalog = arguments.cli.configs
    spec = catalog.spec("artifacts")
    config = spec.load(root) if catalog.path(root, "artifacts").is_file() else ArtifactsConfig()
    store = FileArtifactStore(root / config.directory)
    domain = arguments.subcommand
    training, training_info, training_digest = await _input(
        store, dataset, ResourceKey("aurora", domain, "dataset", "training"), root / arguments.training
    )
    validation, validation_info, validation_digest = await _input(
        store, dataset, ResourceKey("aurora", domain, "dataset", "validation"), root / arguments.validation
    )
    provenance = TrainingProvenance(domain, training_digest, validation_digest, training_info, validation_info)
    result = await asyncio.to_thread(
        backend.train,
        training,
        validation,
        hidden_size=arguments.hidden_size,
        epochs=arguments.epochs,
        learning_rate=arguments.learning_rate,
        seed=arguments.seed,
        provenance=provenance,
    )
    content = await asyncio.to_thread(result.to_bytes)
    model = await store.put(result.model_key, content, media_type=MODEL_MEDIA_TYPE)
    await asyncio.to_thread(write_new_file, output, content)
    return {
        "output": str(output),
        "resource": str(model.ref.key),
        "revision": model.ref.revision,
        "artifact": artifact_data(model),
        "inputs": provenance_data(result.provenance),
        "parameters": result.parameters,
        "final_loss": result.losses[-1],
        "validation": result.metrics,
        "baseline": result.baseline_metrics,
        "training_episodes": result.training_episodes,
        "validation_episodes": result.validation_episodes,
    }


async def _input(
    store: ArtifactStore, dataset: ModuleType, key: ResourceKey, path: Path
) -> tuple[tuple[object, ...], ArtifactInfo, str]:
    """源文件在导入期间变动会失败，后续操作只读取已经固定的资源版本。"""
    info = await store.import_file(key, path, media_type="application/x-ndjson")
    content = await artifact_content(store, info)
    examples = await asyncio.to_thread(dataset.parse_episodes, content)
    digest = await asyncio.to_thread(dataset.episodes_fingerprint, examples)
    return examples, info, digest


MODULE = command_plugin("aurora.cli.commands.train", COMMAND, execute)
