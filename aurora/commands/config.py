"""实现 ``aurora config`` 的只读配置查询。"""

from __future__ import annotations

import sys
import tomllib
from typing import TYPE_CHECKING

from aurora.configuration import load_config
from aurora.utils.exit_code import EXIT_CONFIG_ERROR

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.commander import CommandSpec
    from aurora.config import AuroraConfig

COMMAND: CommandSpec = {
    "name": "config",
    "help": "查看项目配置",
    "subcommands": {
        "list": {"help": "列出全部已注册配置"},
        "show": {
            "help": "显示一份配置的原始 TOML",
            "args": {"name": "配置名称，例如 runtime 或 profiles"},
        },
    },
}


def _list_sources(configuration: AuroraConfig) -> int:
    width = max(len(source.name) for source in configuration.sources)
    for source in configuration.sources:
        sys.stdout.write(f"{source.name.ljust(width)}  |  {source.relative_path}\n")
    return 0


def _show_source(configuration: AuroraConfig, root: Path, name: str) -> int:
    try:
        source = configuration.source(name)
    except KeyError:
        sys.stderr.write(f"未知配置：{name}\n")
        return EXIT_CONFIG_ERROR
    try:
        content = (root / source.relative_path).read_text(encoding="utf-8")
    except OSError as error:
        sys.stderr.write(f"无法读取配置 {name}：{error}\n")
        return EXIT_CONFIG_ERROR
    sys.stdout.write(content)
    if content and not content.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def execute(arguments: argparse.Namespace) -> int:
    """按子命令列出或显示已注册的配置源。"""
    try:
        configuration = load_config(arguments.root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        sys.stderr.write(f"配置加载失败：{error}\n")
        return EXIT_CONFIG_ERROR
    match arguments.subcommand:
        case "list":
            return _list_sources(configuration)
        case "show":
            return _show_source(configuration, arguments.root, str(arguments.name))
        case _:
            return EXIT_CONFIG_ERROR
