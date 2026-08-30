"""读取项目版本与 Git 提交信息。"""

from __future__ import annotations

import subprocess
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def get_project_version(root: Path) -> str | None:
    """返回项目版本号"""
    try:
        with (root / "pyproject.toml").open("rb") as stream:
            return str(tomllib.load(stream)["project"]["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return None


def get_git_revision(root: Path) -> str | None:
    """返回仓库当前提交的短哈希"""
    try:
        result = subprocess.run(
            ["git", "describe", "--always", "--abbrev=7", "--dirty"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    revision = result.stdout.strip()
    return revision or None
