"""实现 ``aurora config``：查看与编辑项目配置。"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from aurora_cli.commands.config.editing import apply_sets, open_in_editor
from aurora_cli.commands.config.overview import render_overview
from aurora_cli.commands.config.render import render_value
from aurora_cli.configs import config_names, config_relative_path, config_spec, initialize_configs, missing_config_files
from aurora_cli.utils.process import EXIT_CONFIG_ERROR

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence
    from pathlib import Path

    from aurora_cli.contracts.command import CommandSpec
    from aurora_cli.contracts.config import ConfigSpec

COMMAND: CommandSpec = {
    "name": "config",
    "help": "查看与编辑项目配置",
    "args": {"name": {"help": "配置名称，例如 runtime；省略时列出全部配置", "nargs": "?"}},
    "options": {
        "--init": "创建缺失的个人配置与配套资源，不覆盖已有文件",
        "--missing": "以 JSON 列出缺失的个人配置文件",
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
    if arguments.init or arguments.missing:
        return _templates(root, arguments)
    if arguments.name is None:
        return _overview(root, check=arguments.check)
    return _named(root, str(arguments.name), arguments)


def _templates(root: Path, arguments: argparse.Namespace) -> int:
    if (arguments.init and arguments.missing) or any((arguments.check, arguments.raw, arguments.edit, arguments.sets)):
        sys.stderr.write("--init / --missing 必须单独使用，可指定配置名称。\n")
        return EXIT_CONFIG_ERROR
    names = None if arguments.name is None else (str(arguments.name),)
    try:
        if arguments.missing:
            sys.stdout.write(json.dumps(missing_config_files(root, names), ensure_ascii=False) + "\n")
        else:
            created = initialize_configs(root, names)
            for path in created:
                sys.stdout.write(f"已创建 {path}。\n")
            if not created:
                sys.stdout.write("个人配置已就绪，已有文件保持不变。\n")
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"配置初始化失败：{error}\n")
        return EXIT_CONFIG_ERROR
    return 0


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
        rendered = render_value(spec.load(root))
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"配置加载失败：{error}\n")
        return EXIT_CONFIG_ERROR
    sys.stdout.write(f"源文件：{spec.path}\n{rendered}\n")
    return 0


def _show_raw(root: Path, name: str) -> int:
    try:
        content = (root / config_relative_path(name)).read_text(encoding="utf-8")
    except OSError as error:
        sys.stderr.write(f"无法读取配置 {name}：{error}\n")
        return EXIT_CONFIG_ERROR
    sys.stdout.write(content if content.endswith("\n") or not content else f"{content}\n")
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
