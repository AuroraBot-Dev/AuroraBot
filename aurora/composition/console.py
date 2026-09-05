"""构造并导出 ``src.console`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.platforms import PLATFORMS_CONFIG, PlatformConfig
from src.console import TerminalConsole

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig

_CONSOLE_PLATFORM_ID = "builtin.console"


class ConsoleOps:
    """console 平台的窄 ops 端口适配器。"""

    def __init__(self, console: PlatformConfig) -> None:
        self._console = console

    def console_status(self) -> dict[str, Any]:
        return {
            "enabled": self._console.enabled,
            "input_to_worldline": True,
            "output_to_worldline": False,
            "scope": "aurora:console",
        }


TERMINAL_CONSOLE = InstanceKey[TerminalConsole]("console.terminal")
CONSOLE_OPS = InstanceKey[ConsoleOps]("console.ops")


def _console_platform(config: AuroraConfig) -> PlatformConfig:
    return next(item for item in config.get(PLATFORMS_CONFIG) if item.id == _CONSOLE_PLATFORM_ID)


def _register(context: CompositionContext) -> None:
    context.provide(TERMINAL_CONSOLE, TerminalConsole(context.require(WORLD_JOURNAL)))
    context.provide(CONSOLE_OPS, ConsoleOps(_console_platform(context.config)))


MODULE_SPEC = ModuleSpec(key=TERMINAL_CONSOLE, requires=(WORLD_JOURNAL,), register=_register)
