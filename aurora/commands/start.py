"""实现 ``aurora start``。"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from aurora.utils.environment import load_project_env

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.config import AuroraConfig

NAME = "start"
CONFIG_ERROR_EXIT_CODE = 2
INTERRUPTED_EXIT_CODE = 130


def _load_configuration(project_root: Path) -> AuroraConfig:
    from aurora.configuration import load_config

    return load_config(project_root)


async def _run_project(configuration: AuroraConfig, *, headless: bool) -> None:
    from aurora.runtime import run_project

    await run_project(configuration, headless=headless)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(NAME, help="启动 AuroraBot 运行时")
    parser.add_argument("--headless", action="store_true", help="不启动本地交互终端")
    parser.set_defaults(executor=execute)


def execute(arguments: argparse.Namespace) -> int:
    try:
        load_project_env(arguments.root)
        configuration = _load_configuration(arguments.root)
        asyncio.run(_run_project(configuration, headless=arguments.headless))
    except KeyboardInterrupt:
        return INTERRUPTED_EXIT_CODE
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"启动失败：{error}\n")
        return CONFIG_ERROR_EXIT_CODE
    return 0
