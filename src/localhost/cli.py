"""Local runner command; deliberately separate from the frozen root bot.py."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from src.config import load_config
from src.localhost.api import create_app
from src.localhost.runtime import AuroraRuntime
from src.localhost.shell import run_console


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
        run_console(AuroraRuntime.create(arguments.root, arguments.profile))
        return
    uvicorn.run(
        create_app(arguments.root, arguments.profile),
        host=configuration.runtime.debug_host,
        port=configuration.runtime.debug_port,
        log_level=configuration.logging_level.lower(),
    )


if __name__ == "__main__":
    main()
