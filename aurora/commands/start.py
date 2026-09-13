"""实现 ``aurora start``。"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from aurora.configuration.platforms import PLATFORMS_CONFIG
from aurora.utils.environment import load_project_env
from aurora.utils.logging import configure_project_logging
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_INTERRUPTED
from aurora.utils.signals import install_stop_handlers, restore_stop_handlers

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.commander import CommandSpec
    from aurora.config import AuroraConfig

_CONSOLE_PLATFORM_ID = "builtin.console"

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


def _console_enabled(configuration: AuroraConfig) -> bool:
    for platform in configuration.get(PLATFORMS_CONFIG).platforms:
        if platform.id == _CONSOLE_PLATFORM_ID:
            return platform.enabled
    return False


async def _run_runtime(configuration: AuroraConfig, *, headless: bool) -> None:
    from src.runtime import run_runtime

    stop = asyncio.Event()
    installed = install_stop_handlers(stop)
    try:
        await run_runtime(configuration, headless=headless, stop_event=stop)
    finally:
        restore_stop_handlers(installed)


def execute(arguments: argparse.Namespace) -> int:
    try:
        load_project_env(arguments.root)
        configuration = _load_configuration(arguments.root)
        configure_project_logging(configuration)
        headless = arguments.headless or not _console_enabled(configuration)
        asyncio.run(_run_runtime(configuration, headless=headless))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"启动失败：{error}\n")
        return EXIT_CONFIG_ERROR
    return 0
