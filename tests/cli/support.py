"""该能力测试共用的离线替身与场景构造。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_cli.commander import build_parser as _build_parser
from aurora_cli.commander import run as _run
from aurora_cli.commands import DEFAULT_REGISTRY

if TYPE_CHECKING:
    import argparse

FAILED_EXIT_CODE = 3
EXPECTED_LINT_COMMANDS = 3


def build_parser() -> argparse.ArgumentParser:
    """以默认命令目录构建顶层解析器。"""
    return _build_parser(DEFAULT_REGISTRY)


def run(arguments: list[str] | None = None) -> int:
    """按默认命令目录运行 CLI 输入，与 aurora_cli.main.main 的分派一致。"""
    return _run(arguments, registry=DEFAULT_REGISTRY)
