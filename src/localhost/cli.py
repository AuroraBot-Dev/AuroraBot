"""Local console and loopback debug API runner."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn

from src.config import load_config
from src.dashboard.api import create_app
from src.localhost.runtime import AuroraRuntime
from src.localhost.shell import run_console
from src.utils.log_utils import get_logger

logger = get_logger("aurora.localhost.cli")


async def _run_combined(root: Path, profile: str | None) -> None:
    runtime = AuroraRuntime.create(root, profile)
    logger.info(
        "combined localhost mode starting host=%s port=%d profile=%s",
        runtime.configuration.dashboard.host,
        runtime.configuration.dashboard.port,
        runtime.configuration.runtime.profile,
    )
    config = uvicorn.Config(
        create_app(root, profile, runtime=runtime, manage_runtime=False),
        host=runtime.configuration.dashboard.host,
        port=runtime.configuration.dashboard.port,
        log_level=runtime.configuration.logging_level.lower(),
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="aurora-debug-api")
    try:
        await run_console(runtime)
    finally:
        server.should_exit = True
        await asyncio.gather(server_task, return_exceptions=True)
        logger.info("combined localhost mode stopped")


def main() -> None:
    """Start the developer-only loopback HTTP server."""
    parser = argparse.ArgumentParser(description="Run AuroraBot locally")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="启动 loopback 开发调试 HTTP API")
    subcommands.add_parser("console", help="启动分层本地开发控制台")
    arguments = parser.parse_args()
    configuration = load_config(arguments.root, arguments.profile)
    if arguments.command == "console":
        logger.info("console mode selected profile=%s", configuration.runtime.profile)
        asyncio.run(run_console(AuroraRuntime.create(arguments.root, arguments.profile)))
        return
    if arguments.command is None:
        asyncio.run(_run_combined(arguments.root, arguments.profile))
        return
    logger.info(
        "debug API serve mode selected host=%s port=%d profile=%s",
        configuration.dashboard.host,
        configuration.dashboard.port,
        configuration.runtime.profile,
    )
    uvicorn.run(
        create_app(arguments.root, arguments.profile),
        host=configuration.dashboard.host,
        port=configuration.dashboard.port,
        log_level=configuration.logging_level.lower(),
    )


if __name__ == "__main__":
    main()
