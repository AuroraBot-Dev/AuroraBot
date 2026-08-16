"""实现 ``aurora donk`` 子命令。"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any

from donk.main import cli as donk_cli

from aurora.process import console, invoke_cli

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

NAME = "donk"


def _read_version(root: Path) -> str | None:
    """读取 pyproject.toml 当前版本号，失败或不可用时返回 None。"""
    try:
        with (root / "pyproject.toml").open("rb") as file:
            return str(tomllib.load(file)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None


def register(subparsers: Any) -> None:
    """向子解析器注册 donk 命令及其 show/major/minor/patch 子命令。"""
    parser = subparsers.add_parser(NAME, help="自动版本管理")
    sub = parser.add_subparsers(dest="donk_command", required=True)
    sub.add_parser("show", help="显示当前版本号")
    sub.add_parser("major", help="升级主版本号")
    sub.add_parser("minor", help="升级次版本号")
    sub.add_parser("patch", help="升级修订版本号")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    """执行 donk 子命令的运行逻辑并输出版本更新结果。"""
    subcommand = arguments.donk_command
    pyproject = str((arguments.root / "pyproject.toml").resolve())
    exit_code = invoke_cli(donk_cli, [subcommand, pyproject], "donk")
    if exit_code != 0:
        console.print(f"[bold red]donk {subcommand} 执行失败[/bold red]")
        return exit_code
    version = _read_version(arguments.root)
    if subcommand == "show":
        if version:
            console.print(f"[bold green]当前版本:[/bold green] [bold cyan]{version}[/bold cyan]")
    elif version:
        console.print(f"[bold green]版本已更新为:[/bold green] [bold cyan]{version}[/bold cyan]")
    return 0
