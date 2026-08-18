"""加载项目级本地环境变量。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from pathlib import Path


def load_project_env(project_root: Path) -> bool:
    """读取项目根目录的 ``.env``，但不覆盖已有进程环境变量。"""
    return load_dotenv(project_root / ".env", override=False)
