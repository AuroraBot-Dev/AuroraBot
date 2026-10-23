"""识别当前运行平台并给出面向用户的系统名称。"""

from __future__ import annotations

import sys

_OS_NAMES = {
    "win32": "Windows",
    "darwin": "macOS",
    "linux": "Linux",
}


def detect_os() -> str:
    """返回当前平台面向用户的系统名称（Windows / macOS / Linux，未知时回退原始平台名）。"""
    return _OS_NAMES.get(sys.platform, sys.platform)


def is_linux() -> bool:
    return sys.platform == "linux"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"
