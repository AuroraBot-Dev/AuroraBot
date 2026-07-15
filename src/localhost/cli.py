"""Local runner command; deliberately separate from the frozen root bot.py."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn

from src.config import load_config
from src.localhost.api import create_app
from src.localhost.runtime import AuroraRuntime
from src.localhost.shell import run_console


async def _run_combined(root: Path, profile: str | None) -> None:
    runtime = AuroraRuntime.create(root, profile)
    config = uvicorn.Config(
        create_app(root, profile, runtime=runtime, manage_runtime=False),
        host=runtime.configuration.runtime.debug_host,
        port=runtime.configuration.runtime.debug_port,
        log_level=runtime.configuration.logging_level.lower(),
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="aurora-debug-api")
    try:
        await run_console(runtime)
    finally:
        server.should_exit = True
        await asyncio.gather(server_task, return_exceptions=True)


def main() -> None:
    """Start the developer-only loopback HTTP server."""
    parser = argparse.ArgumentParser(description="Run AuroraBot vNext locally")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="启动 loopback 开发调试 HTTP API")
    subcommands.add_parser("console", help="启动分层本地开发控制台")
    arguments = parser.parse_args()
    configuration = load_config(arguments.root, arguments.profile)
    if arguments.command == "console":
        asyncio.run(run_console(AuroraRuntime.create(arguments.root, arguments.profile)))
        return
    if arguments.command is None:
        asyncio.run(_run_combined(arguments.root, arguments.profile))
        return
    uvicorn.run(
        create_app(arguments.root, arguments.profile),
        host=configuration.runtime.debug_host,
        port=configuration.runtime.debug_port,
        log_level=configuration.logging_level.lower(),
    )


if __name__ == "__main__":
    main()
