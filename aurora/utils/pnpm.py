"""在子模块目录中执行 pnpm 脚本并统一呈现结果。"""

from __future__ import annotations

import shutil
import sys
from typing import TYPE_CHECKING

from aurora.utils.exit_code import EXIT_FAILURE
from aurora.utils.process import run_process

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def run_pnpm(script: str, passthrough: Sequence[str], directory: Path, label: str) -> int:
    if not (directory / "package.json").is_file():
        sys.stderr.write(f"{label} 子模块未初始化，请先运行 aurora setup。\n")
        return EXIT_FAILURE
    if shutil.which("pnpm") is None:
        sys.stderr.write("未找到 pnpm，请先安装并加入 PATH 后重试。\n")
        return EXIT_FAILURE
    return run_process(("pnpm", script, *passthrough), directory)
