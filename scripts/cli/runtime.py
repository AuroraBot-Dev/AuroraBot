"""Installed CLI commands for the localhost composition entry point."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def register(sub: Any) -> None:
    """Register runtime commands without assuming a source checkout or ``uv``."""
    for name, help_text in (
        ("serve", "启动开发调试 HTTP API 服务器"),
        ("console", "启动分层本地开发控制台"),
    ):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("--root", type=Path, default=Path.cwd())
        parser.add_argument("--profile")


def _run(args: argparse.Namespace, command: str | None) -> int:
    from src.dashboard.cli import main

    argv = ["--root", str(args.root)]
    if args.profile:
        argv.extend(("--profile", args.profile))
    if command is not None:
        argv.append(command)
    main(argv)
    return 0


def serve(args: argparse.Namespace) -> int:
    return _run(args, "serve")


def console(args: argparse.Namespace) -> int:
    return _run(args, "console")


def default(_args: argparse.Namespace) -> int:
    """Keep the interactive combined mode for source checkouts."""
    return _run(argparse.Namespace(root=Path.cwd(), profile=None), None)
