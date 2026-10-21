"""将 ``aurora setup`` 转交统一工程引导入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_cli.utils.process import run_process

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora_cli.contracts.command import CommandSpec

COMMAND: CommandSpec = {
    "name": "setup",
    "help": "初始化依赖与个人配置",
    "options": {
        "--python": "同步 Python 依赖",
        "--config": "从模板创建个人配置",
        "--env": "从模板创建环境文件",
        "--docs": "安装文档站所在的应用工作区依赖",
    },
}
_FLAG_STEPS = ("python", "config", "env", "docs")


def execute(arguments: argparse.Namespace) -> int:
    root: Path = arguments.root
    flags = tuple(f"--{name}" for name in _FLAG_STEPS if getattr(arguments, name))
    return run_process(("node", str(root / "scripts" / "setup.ts"), "--no-link", *flags), root)
