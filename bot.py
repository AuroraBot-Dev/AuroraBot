"""AuroraBot 的常驻 Runtime 与 Dashboard 组合入口。"""

from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from src.dashboard.api import create_app
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


async def run_bot(
    root: Path,
    profile: str | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    headless: bool = False,
) -> None:
    """创建唯一 Runtime，并持续推进认知循环与可选 Dashboard。"""
    runtime = AuroraRuntime.create(_resolve_root(root), profile)
    configure_logging(runtime.configuration.logging_level)
    stop = stop_event or asyncio.Event()
    installed_signals = _install_stop_handlers(stop) if stop_event is None else ()
    logger.info(
        "bot service started profile=%s workspace=%s dashboard=%s",
        runtime.configuration.runtime.profile,
        runtime.configuration.runtime.workspace,
        not headless,
    )
    try:
        await runtime.start()
        if headless:
            await runtime.run_forever(stop)
        else:
            await _run_dashboard(runtime, stop)
    finally:
        loop = asyncio.get_running_loop()
        for installed_signal in installed_signals:
            loop.remove_signal_handler(installed_signal)
        await runtime.shutdown()
        logger.info("bot service stopped profile=%s", runtime.configuration.runtime.profile)


async def _run_dashboard(runtime: AuroraRuntime, stop: asyncio.Event) -> None:
    dashboard = runtime.configuration.dashboard
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(runtime.configuration.root, runtime=runtime, manage_runtime=False),
            host=dashboard.host,
            port=dashboard.port,
            log_level=runtime.configuration.logging_level.lower(),
        )
    )
    runtime_task = asyncio.create_task(runtime.run_forever(stop), name="aurora-bot-loop")
    server_task = asyncio.create_task(server.serve(), name="aurora-dashboard-server")
    stop_task = asyncio.create_task(stop.wait(), name="aurora-stop-watcher")
    done, _pending = await asyncio.wait(
        {runtime_task, server_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    stop.set()
    server.should_exit = True
    await asyncio.gather(runtime_task, server_task, return_exceptions=True)
    stop_task.cancel()
    await asyncio.gather(stop_task, return_exceptions=True)
    for task in done:
        if task != stop_task and not task.cancelled():
            task.result()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AuroraBot cognitive loop")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="项目根目录（默认是 bot.py 所在目录）",
    )
    parser.add_argument("--profile", help="config/profiles 下的配置 profile 名称")
    parser.add_argument("--headless", action="store_true", help="只运行认知循环，不启动 Dashboard HTTP/WS")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parse_args(argv)
    asyncio.run(run_bot(arguments.root, arguments.profile, headless=arguments.headless))


if __name__ == "__main__":
    main()
