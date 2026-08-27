"""执行子进程并统一呈现退出状态。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

from aurora.utils.exit_code import EXIT_FAILURE, EXIT_INTERRUPTED

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


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
