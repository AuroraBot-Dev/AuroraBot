"""Bot 进程门面、装配入口、终端分派、文本呈现与装配工厂。"""

from aurora_bot.runtime.assembly import assemble_runtime, compose_runtime
from aurora_bot.runtime.core import AuroraRuntime
from aurora_bot.runtime.factory import RuntimeFactory, create_runtime
from aurora_bot.runtime.presenter import CognitionTextPresenter
from aurora_bot.runtime.run import run_runtime
from aurora_bot.runtime.terminal import TerminalCommandDispatcher

__all__ = [
    "AuroraRuntime",
    "CognitionTextPresenter",
    "RuntimeFactory",
    "TerminalCommandDispatcher",
    "assemble_runtime",
    "compose_runtime",
    "create_runtime",
    "run_runtime",
]
