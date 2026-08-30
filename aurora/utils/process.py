"""执行子进程并统一呈现退出状态；约定进程退出码。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

EXIT_FAILURE = 1
EXIT_CONFIG_ERROR = 2
EXIT_INTERRUPTED = 130


def run_process(command: Sequence[str], root: Path) -> int:
    sys.stdout.write(f"\n>>> {' '.join(command)}\n")
    sys.stdout.flush()
    try:
        result = subprocess.run(_resolve_command(command), cwd=root, check=False)
    except FileNotFoundError:
        sys.stderr.write(f"未找到命令 {command[0]}，请先安装并加入 PATH 后重试。\n")
        return EXIT_FAILURE
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    if result.returncode != 0:
        sys.stderr.write(f"命令失败，退出码 {result.returncode}。\n")
    return result.returncode


def _resolve_command(command: Sequence[str]) -> list[str]:
    executable = shutil.which(command[0])
    if executable is None:
        return list(command)
    return [executable, *command[1:]]


def run_pnpm(script: str, passthrough: Sequence[str], directory: Path, label: str) -> int:
    """在子模块目录中执行 pnpm 脚本并统一呈现结果。"""
    if not (directory / "package.json").is_file():
        sys.stderr.write(f"{label} 子模块未初始化，请先运行 aurora setup。\n")
        return EXIT_FAILURE
    return run_process(("pnpm", script, *passthrough), directory)
