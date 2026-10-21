"""提供 ``aurora playground`` 入口，参数与标准流交给仓库内的 Playground。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora_cli.plugins import command_plugin
from aurora_cli.utils.process import EXIT_CONFIG_ERROR, run_process

if TYPE_CHECKING:
    import argparse

    from aurora_cli.contracts.command import CommandSpec

COMMAND: CommandSpec = {
    "name": "playground",
    "help": "启动模块交互 Playground（需要源码仓库）",
    "passthrough": "透传给 Playground 的参数，例如 --tui、--pretty、--module kernel",
}


def execute(arguments: argparse.Namespace) -> int:
    root = arguments.root
    if not (root / "playground" / "__main__.py").is_file():
        sys.stderr.write("未找到 Playground；请在 AuroraBot 源码仓库根目录运行，或用 aurora --root 指定仓库。\n")
        return EXIT_CONFIG_ERROR
    forwarded = arguments.passthrough
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    # 使用当前环境并继承标准流，保留 TTY 与 JSON Lines，不向 stdout 写启动横幅。
    return run_process((sys.executable, "-m", "playground", *forwarded), root, announce=False)


MODULE = command_plugin("aurora.cli.commands.playground", COMMAND, execute)
