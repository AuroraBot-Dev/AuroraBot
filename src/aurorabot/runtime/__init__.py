"""Bot 进程门面、装配入口、终端分派、文本呈现与装配工厂。"""

from aurorabot.runtime.assembly import assemble_runtime, compose_runtime
from aurorabot.runtime.core import AuroraRuntime
from aurorabot.runtime.factory import RuntimeFactory, create_runtime
from aurorabot.runtime.presenter import TreeTextPresenter
from aurorabot.runtime.run import run_runtime
from aurorabot.runtime.terminal import TerminalCommandDispatcher

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
