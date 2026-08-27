"""实现 ``aurora start``。"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from aurora.utils.environment import load_project_env
from aurora.utils.exit_code import EXIT_CONFIG_ERROR, EXIT_INTERRUPTED

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.commander import CommandSpec
    from aurora.config import AuroraConfig

COMMAND: CommandSpec = {
    "name": "start",
    "help": "启动 AuroraBot 运行时",
    "options": {
        "--headless": "不启动本地交互终端",
    },
}


def _load_configuration(project_root: Path) -> AuroraConfig:
    from aurora.configuration import load_config

    return load_config(project_root)


async def _run_project(configuration: AuroraConfig, *, headless: bool) -> None:
    from aurora.runtime import run_project

    await run_project(configuration, headless=headless)


def execute(arguments: argparse.Namespace) -> int:
    try:
        load_project_env(arguments.root)
        configuration = _load_configuration(arguments.root)
        asyncio.run(_run_project(configuration, headless=arguments.headless))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"启动失败：{error}\n")
        return EXIT_CONFIG_ERROR
    return 0
