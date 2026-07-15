"""AuroraBot vNext 的常驻无头入口。"""

from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path
from typing import TYPE_CHECKING

from src.localhost.runtime import AuroraRuntime
from src.utils.log_utils import configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence


logger = get_logger("aurora.bot")


def _resolve_root(root: Path) -> Path:
    return root.resolve()


def _install_stop_handlers(stop: asyncio.Event) -> tuple[signal.Signals, ...]:
    """让支持 asyncio 信号处理的平台可以优雅停止常驻循环。"""
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for candidate in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(candidate, stop.set)
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(candidate)
    return tuple(installed)


async def run_bot(root: Path, profile: str | None = None, *, stop_event: asyncio.Event | None = None) -> None:
    """创建唯一的 vNext Runtime，并持续推进认知循环直至停止。"""
    runtime = AuroraRuntime.create(_resolve_root(root), profile)
    configure_logging(runtime.configuration.logging_level)
    stop = stop_event or asyncio.Event()
    installed_signals = _install_stop_handlers(stop) if stop_event is None else ()
    logger.info(
        "headless bot loop started profile=%s workspace=%s",
        runtime.configuration.runtime.profile,
        runtime.configuration.runtime.workspace,
    )
    try:
        await runtime.run_forever(stop)
    finally:
        loop = asyncio.get_running_loop()
        for installed_signal in installed_signals:
            loop.remove_signal_handler(installed_signal)
        await runtime.shutdown()
        logger.info("headless bot loop stopped profile=%s", runtime.configuration.runtime.profile)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AuroraBot vNext cognitive loop")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="项目根目录（默认是 bot.py 所在目录）",
    )
    parser.add_argument("--profile", help="config/profiles 下的配置 profile 名称")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parse_args(argv)
    asyncio.run(run_bot(arguments.root, arguments.profile))


if __name__ == "__main__":
    main()
