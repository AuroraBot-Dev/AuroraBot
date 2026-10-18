"""训练并验证 Bot 的节律和记忆策略，导出明确版本的模型权重。"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from aurora.utils.process import EXIT_FAILURE

if TYPE_CHECKING:
    import argparse

    from aurora.contracts.command import CommandSpec, SubcommandSpec


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
        package = {"rhythm": "src.rhythm", "memory": "src.memory_model"}[arguments.subcommand]
        dataset = import_module(f"{package}.dataset")
        backend = import_module(f"{package}.training")
    except ModuleNotFoundError as error:
        if error.name not in {"torch", "numpy"}:
            raise
        sys.stderr.write("训练依赖未安装，请运行 uv sync --extra learning。\n")
        return EXIT_FAILURE
    try:
        training = dataset.read_episodes(arguments.root / arguments.training)
        validation = dataset.read_episodes(arguments.root / arguments.validation)
        output = arguments.root / arguments.output
        if output.exists():
            raise ValueError("输出权重已经存在，请为这次训练指定新的文件")
        result = backend.train(
            training,
            validation,
            hidden_size=arguments.hidden_size,
            epochs=arguments.epochs,
            learning_rate=arguments.learning_rate,
            seed=arguments.seed,
        )
        ref = result.save(output)
    except (ValueError, OSError) as error:
        sys.stderr.write(f"模型训练失败：{error}\n")
        return EXIT_FAILURE
    sys.stdout.write(
        json.dumps(
            {
                "output": str(output),
                "resource": str(ref.key),
                "revision": ref.revision,
                "parameters": result.parameters,
                "final_loss": result.losses[-1],
                "validation": result.metrics,
                "baseline": result.baseline_metrics,
                "training_episodes": result.training_episodes,
                "validation_episodes": result.validation_episodes,
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    return 0
