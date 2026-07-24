"""实现 ``aurora reload`` 子命令。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

NAME = "reload"


def register(subparsers: Any) -> None: ...


def execute(arguments: argparse.Namespace) -> int: ...
