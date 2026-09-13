"""实现 ``aurora config``：查看与编辑项目配置。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from aurora.commands.config.detail import read_source, render_effective
from aurora.commands.config.editing import apply_sets, open_in_editor
from aurora.commands.config.overview import render_overview
from aurora.configuration import config_names, config_spec
from aurora.utils.process import EXIT_CONFIG_ERROR

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence
    from pathlib import Path

    from aurora.commander import CommandSpec
    from aurora.config import ConfigSpec

COMMAND: CommandSpec = {
    "name": "config",
    "help": "查看与编辑项目配置",
    "args": {"name": {"help": "配置名称，例如 runtime；省略时列出全部配置", "nargs": "?"}},
    "options": {
        "--check": "列出全部配置时逐个加载校验（较慢）",
        "--raw": "显示源文件的原始 TOML",
        "--edit": "用 $EDITOR 打开源文件",
        "--set": {
            "help": "改写源文件字段，格式 KEY=VALUE，可重复",
            "action": "append",
            "dest": "sets",
            "metavar": "KEY=VALUE",
        },
    },
}

_LOAD_ERRORS = (OSError, ValueError, TypeError, KeyError)


def execute(arguments: argparse.Namespace) -> int:
    """按名称查看配置，省略名称时列出全部；``--edit``/``--set`` 显式写入源文件。"""
    root: Path = arguments.root
    if arguments.name is None:
        return _overview(root, check=arguments.check)
    return _named(root, str(arguments.name), arguments)


def _overview(root: Path, *, check: bool) -> int:
    table, failures = render_overview(root, config_names(), check=check)
    sys.stdout.write(f"{table}\n")
    return EXIT_CONFIG_ERROR if failures else 0


def _named(root: Path, name: str, arguments: argparse.Namespace) -> int:
    if name not in config_names():
        sys.stderr.write(f"未知配置：{name}\n")
        return EXIT_CONFIG_ERROR
    spec = config_spec(name)
    if arguments.sets and arguments.edit:
        sys.stderr.write("--set 与 --edit 不能同时使用。\n")
        return EXIT_CONFIG_ERROR
    if arguments.sets:
        return _apply_sets(root, spec, arguments.sets)
    if arguments.edit:
        return _edit(root, spec)
    if arguments.raw:
        return _show_raw(root, name)
    return _show_effective(root, spec)


def _show_effective(root: Path, spec: ConfigSpec[Any]) -> int:
    try:
        rendered = render_effective(root, spec)
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"配置加载失败：{error}\n")
        return EXIT_CONFIG_ERROR
    sys.stdout.write(f"源文件：{spec.path}\n{rendered}\n")
    return 0


def _show_raw(root: Path, name: str) -> int:
    try:
        content = read_source(root, name)
    except OSError as error:
        sys.stderr.write(f"无法读取配置 {name}：{error}\n")
        return EXIT_CONFIG_ERROR
    sys.stdout.write(content)
    return 0


def _apply_sets(root: Path, spec: ConfigSpec[Any], assignments: Sequence[str]) -> int:
    try:
        apply_sets(root / spec.path, assignments)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        sys.stderr.write(f"无法修改配置 {spec.name}：{error}\n")
        return EXIT_CONFIG_ERROR
    return _report_update(root, spec)


def _edit(root: Path, spec: ConfigSpec[Any]) -> int:
    exit_code = open_in_editor(root, root / spec.path)
    if exit_code != 0:
        return exit_code
    return _report_update(root, spec)


def _report_update(root: Path, spec: ConfigSpec[Any]) -> int:
    try:
        spec.load(root)
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"配置校验失败：{error}\n")
        return EXIT_CONFIG_ERROR
    sys.stdout.write(f"已更新 {spec.path}，配置校验通过。\n")
    return 0
