"""Bot 进程门面、终端分派、文本呈现与装配工厂。"""

from src.runtime.core import AuroraRuntime
from src.runtime.factory import create_runtime
from src.runtime.presenter import TreeTextPresenter
from src.runtime.terminal import TerminalCommandDispatcher

__all__ = ["AuroraRuntime", "TerminalCommandDispatcher", "TreeTextPresenter", "create_runtime"]
