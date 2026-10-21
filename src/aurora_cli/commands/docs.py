"""实现 ``aurora docs``：在 apps/docsite 中运行 pnpm 脚本。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_cli.utils.process import run_pnpm

if TYPE_CHECKING:
    import argparse

    from aurora_cli.contracts.command import CommandSpec

COMMAND: CommandSpec = {
    "name": "docs",
    "help": "在 apps/docsite 中运行 pnpm 脚本",
    "args": {"script": "pnpm 脚本名，例如 dev 或 build"},
    "passthrough": "透传给 pnpm 的附加参数",
}


def execute(arguments: argparse.Namespace) -> int:
    return run_pnpm(
        str(arguments.script),
        arguments.passthrough,
        arguments.root / "apps" / "docsite",
        "docs",
    )
