"""终端分派与控制的最小公共契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


def is_terminal_command(text: str) -> bool:
    """斜杠开头的输入只交给本地命令分派，不进入世界。"""
    return text.startswith("/")


class TerminalControl(StrEnum):
    NONE = "none"
    CLEAR = "clear"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class TerminalResponse:
    text: str | None = None
    control: TerminalControl = TerminalControl.NONE
    is_error: bool = False
