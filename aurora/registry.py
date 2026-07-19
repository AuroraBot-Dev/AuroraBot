"""Declarative registry for the process-level Aurora CLI."""

from __future__ import annotations

from typing import Any

from aurora.commands import check

COMMAND_MODULES = (check,)


def register_commands(subparsers: Any) -> None:
    for module in COMMAND_MODULES:
        module.register(subparsers)
