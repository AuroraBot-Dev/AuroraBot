"""实现 ``aurora start``。"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from aurora_cli.utils.environment import load_project_env
from aurora_cli.utils.logging import configure_project_logging
from aurora_cli.utils.process import EXIT_CONFIG_ERROR, EXIT_INTERRUPTED
from aurora_cli.utils.signals import install_stop_handlers, restore_stop_handlers

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora_cli.contracts.command import CommandSpec
    from aurora_cli.contracts.config import AuroraConfig

_CONSOLE_PLATFORM_ID = "aurora:platform/console"

COMMAND: CommandSpec = {
    "name": "start",
    "help": "启动 AuroraBot 运行时",
    "options": {
        "--headless": "不启动本地交互终端",
    },
}


def _load_config(project_root: Path) -> AuroraConfig:
    from aurora_cli.configs import initialize_configs, load_config

    initialize_configs(project_root)
    return load_config(project_root)


def _console_enabled(config: AuroraConfig) -> bool:
    from aurora_cli.configs.platforms import CONFIG_SPEC as PLATFORMS_CONFIG

    for platform in config.get(PLATFORMS_CONFIG).platforms:
        if platform.id == _CONSOLE_PLATFORM_ID:
            return platform.enabled
    return False


async def _run_runtime(config: AuroraConfig, *, headless: bool) -> None:
    from aurora_bot.runtime import run_runtime

    stop = asyncio.Event()
    installed = install_stop_handlers(stop)
    try:
        await run_runtime(config, headless=headless, stop_event=stop)
    finally:
        restore_stop_handlers(installed)


def _failure_lines(error: BaseException) -> list[str]:
    """终端逐项显示异常组，保留原始运行错误和释放错误。"""
    if isinstance(error, BaseExceptionGroup):
        lines = []
        for child in error.exceptions:
            lines.extend(_failure_lines(child))
        return lines
    return [str(error)]


def execute(arguments: argparse.Namespace) -> int:
    try:
        load_project_env(arguments.root)
        config = _load_config(arguments.root)
        configure_project_logging(config)
        headless = arguments.headless or not _console_enabled(config)
        asyncio.run(_run_runtime(config, headless=headless))
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except ExceptionGroup as error:
        sys.stderr.write("运行失败：\n" + "\n".join(_failure_lines(error)) + "\n")
        return EXIT_CONFIG_ERROR
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"启动失败：{error}\n")
        return EXIT_CONFIG_ERROR
    return 0
