"""终端分派与控制的最小契约；权威定义在公共契约层，console 侧仅重导出。"""

from __future__ import annotations

from src.contracts.console import TerminalControl, TerminalResponse
from src.contracts.pkgs.runtime import TerminalDispatcher

__all__ = ["TerminalControl", "TerminalDispatcher", "TerminalResponse"]
