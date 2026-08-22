"""加载项目级本地环境变量。"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from pathlib import Path


def load_project_env(project_root: Path) -> bool:
    """读取项目根目录的 ``.env``，但不覆盖已有进程环境变量。"""
    return load_dotenv(project_root / ".env", override=False)


def get_project_version(root: Path) -> str | None:
    try:
        with (root / "pyproject.toml").open("rb") as stream:
            return str(tomllib.load(stream)["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return None
