"""Bot 进程门面、装配入口、终端分派、文本呈现与装配工厂。"""

from src.runtime.assembly import assemble_runtime, compose_runtime
from src.runtime.core import AuroraRuntime
from src.runtime.factory import RuntimeFactory, create_runtime
from src.runtime.presenter import TreeTextPresenter
from src.runtime.run import run_runtime
from src.runtime.terminal import TerminalCommandDispatcher

__all__ = [
    "AuroraRuntime",
    "RuntimeFactory",
    "TerminalCommandDispatcher",
    "TreeTextPresenter",
    "assemble_runtime",
    "compose_runtime",
    "create_runtime",
    "run_runtime",
]
