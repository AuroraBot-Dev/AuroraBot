"""展示项目标志、介绍、版本与相关链接。"""

import platform
import shutil
import subprocess
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TextIO

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ...declarations import CommandContext, command_plugin

DEFINITIONS = {"about": {"help": "了解 AuroraBot 与当前运行环境"}}
LOGO = """\
                              ▄          ▄
▄▀▀█ █  █ █▀▀▀ █▀▀█ █▀▀▀ ▄▀▀█ █▀▀█ █▀▀█ ▀█▀▀
█░░█ █░░█ █    █░░█ █    █░░█ █░░█ █░░█  █░░
▀▀▀▀ ▀▀▀▀ ▀    ▀▀▀▀ ▀    ▀▀▀▀ ▀▀▀▀ ▀▀▀▀  ▀▀▀
"""
ABOUT = """\
你说得对, 但是 AuroraBot 是新一代内驱式, 自主决策的 Bot 框架,
它为 Agent 提供可以"生活"的运行环境. 她有自己的人格、状态, 可
以在需要时与人和外部世界建立联系.  在她的世界里, 所有的消息都
有一个"媒介": 你发给她的消息也必须先成为一个应用通知喔~
"""


def execute(root: Path, output: TextIO) -> int:
    rows = [("系统", platform.platform()), ("Python", platform.python_version())]
    project = root / "pyproject.toml"
    if project.is_file():
        data = tomllib.loads(project.read_text(encoding="utf-8")).get("project", {})
        if data.get("name") == "aurorabot-ai":
            rows.append(("项目版本", str(data.get("version", "未声明"))))
    for distribution in ("aurorabot-ai", "aurora-cli"):
        try:
            rows.append((distribution, version(distribution)))
        except PackageNotFoundError:
            pass
    git = shutil.which("git")
    if git and root.is_dir():
        result = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            rows.append(("提交", result.stdout.strip()))
    rows.extend(
        (
            ("文档站", "https://www.aurorabot.org/"),
            ("项目地址", "https://www.github.com/AuroraBot-Dev/AuroraBot"),
            ("爱发电", "https://ifdian.net/a/aurorabot"),
        )
    )
    print(f"{LOGO}\n\n{ABOUT}\n", file=output)
    table = Table("项目", "内容", box=box.SIMPLE, show_edge=False)
    for label, value in rows:
        table.add_row(Text(label), Text(value))
    Console(file=output).print(table)
    return 0


def dispatch(context: CommandContext) -> int:
    return execute(context.root, context.output)


def plugin():
    return command_plugin(__name__, {"about": {**DEFINITIONS["about"], "executor": dispatch}})
