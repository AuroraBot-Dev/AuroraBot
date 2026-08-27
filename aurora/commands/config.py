"""实现 ``aurora config`` 的只读配置查询。"""

from __future__ import annotations

import sys
import tomllib
from typing import TYPE_CHECKING

from aurora.configuration import load_config

if TYPE_CHECKING:
    import argparse

NAME = "config"
_LIST = "list"
_SHOW = "show"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="查看项目配置")
    commands = parser.add_subparsers(dest="config_command", required=True)
    commands.add_parser(_LIST, help="列出全部已注册配置")
    show = commands.add_parser(_SHOW, help="显示一份配置的原始 TOML")
    show.add_argument("name", help="配置名称，例如 runtime 或 profiles.dev")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    try:
        configuration = load_config(arguments.root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        sys.stderr.write(f"配置加载失败：{error}\n")
        return 2
    if arguments.config_command == _LIST:
        for source in configuration.sources:
            sys.stdout.write(f"{source.name}\t{source.relative_path}\n")
        return 0
    name = str(arguments.name)
    try:
        source = configuration.source(name)
    except KeyError:
        sys.stderr.write(f"未知配置：{name}\n")
        return 2
    try:
        content = (arguments.root / source.relative_path).read_text(encoding="utf-8")
    except OSError as error:
        sys.stderr.write(f"无法读取配置 {name}：{error}\n")
        return 2
    sys.stdout.write(content)
    if content and not content.endswith("\n"):
        sys.stdout.write("\n")
    return 0
