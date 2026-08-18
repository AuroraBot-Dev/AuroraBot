"""CLI 命令共享的子进程执行边界。"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def run_process(command: Sequence[str], root: Path) -> int:
    sys.stdout.write(f"\n>>> {' '.join(command)}\n")
    sys.stdout.flush()
    try:
        result = subprocess.run(command, cwd=root, check=False)
    except KeyboardInterrupt:
        return 130
    if result.returncode != 0:
        sys.stderr.write(f"命令失败，退出码 {result.returncode}。\n")
    return result.returncode
