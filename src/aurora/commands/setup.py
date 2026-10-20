"""实现 ``aurora setup`` 完整项目引导。"""

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING

from aurora.utils.process import EXIT_FAILURE, run_process

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.contracts.command import CommandSpec

COMMAND: CommandSpec = {
    "name": "setup",
    "help": "初始化依赖与个人配置",
    "options": {
        "--python": "同步 Python 依赖",
        "--config": "从模板创建个人配置",
        "--env": "从模板创建环境文件",
        "--docs": "安装文档站所在的应用工作区依赖",
        "--panel": "安装面板所在的应用工作区依赖",
    },
}
_FLAG_STEPS = ("python", "config", "env", "docs", "panel")


def _selection(arguments: argparse.Namespace) -> dict[str, bool]:
    """未指定任何开关时全选；指定开关时只执行选中的步骤。"""
    selected = {name: bool(getattr(arguments, name)) for name in _FLAG_STEPS}
    if not any(selected.values()):
        return dict.fromkeys(_FLAG_STEPS, True)
    return selected


def _ensure_config_copy(root: Path) -> bool:
    template = root / "config.example"
    personal = root / "config"
    if personal.is_dir():
        sys.stdout.write("config/ 已存在，跳过复制。\n")
        return True
    if not template.is_dir():
        sys.stderr.write(f"未找到配置模板 {template}。\n")
        return False
    shutil.copytree(template, personal)
    sys.stdout.write("已从 config.example/ 复制个人配置到 config/。\n")
    return True


def _ensure_env_copy(root: Path) -> bool:
    template = root / ".env.example"
    personal = root / ".env"
    if personal.is_file():
        sys.stdout.write(".env 已存在，跳过复制。\n")
        return True
    if not template.is_file():
        sys.stderr.write(f"未找到环境模板 {template}。\n")
        return False
    shutil.copyfile(template, personal)
    sys.stdout.write("已从 .env.example 复制环境文件到 .env。\n")
    return True


def execute(arguments: argparse.Namespace) -> int:
    root: Path = arguments.root
    selected = _selection(arguments)
    steps: list[tuple[str, tuple[str, ...], Path]] = []
    if selected["python"]:
        steps.append(("同步 Python 依赖", ("uv", "sync"), root))
    if selected["config"] and not _ensure_config_copy(root):
        return EXIT_FAILURE
    if selected["env"] and not _ensure_env_copy(root):
        return EXIT_FAILURE
    if selected["docs"] or selected["panel"]:
        if shutil.which("pnpm") is None:
            sys.stderr.write("未找到 pnpm，跳过应用工作区依赖安装；安装 pnpm 后重新运行本命令即可。\n")
        else:
            steps.append(("安装应用工作区依赖", ("pnpm", "install", "--frozen-lockfile"), root))
    for label, command, cwd in steps:
        if run_process(command, cwd) != 0:
            sys.stderr.write(f"{label}失败。\n")
            return EXIT_FAILURE
    sys.stdout.write("\n项目引导完成。\n")
    return 0
