"""``src.console`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.console.events import CONSOLE_SCOPE
from src.console.shell import TerminalConsole
from src.contracts import FRONT_BINDINGS, Front, FrontContext, FrontIO
from src.contracts.pkgs.console import TerminalConsole as TerminalConsolePort
from src.contracts.pkgs.runtime import TerminalDispatcher
from src.contracts.pkgs.world import WorldWriter
from src.contracts.scope import ScopeDeclaration, ScopeKind
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio

    from src.contracts import FrontBinding


@module(
    name="console",
    provides=TerminalConsolePort,
    requires=(TerminalConsolePort, WorldWriter),
    contributes=FRONT_BINDINGS,
    scopes=ScopeDeclaration(CONSOLE_SCOPE, ScopeKind.RESOURCE, "本地终端输入先进入的世界线；渲染输出不进入世界线。"),
)
def build(context: ModuleContext) -> TerminalConsolePort:
    """交互前台绑定实际选中的终端端口。"""
    console = context.get_optional(TerminalConsolePort)
    if console is None:
        console = TerminalConsole(context.get(WorldWriter))
    context.contribute(FRONT_BINDINGS, _bind_console(console))
    return console


def _bind_console(console: TerminalConsolePort) -> FrontBinding:
    """把本地终端包装为交互式前台；所需能力由运行上下文按需提供。"""

    def bind(context: FrontContext) -> Front:
        dispatcher = context.get(TerminalDispatcher)
        io = context.get(FrontIO)

        async def run(stop: asyncio.Event) -> None:
            await console.run(dispatcher, stop_event=stop, readline=io.readline, output=io.output)

        return Front(run, interactive=True)

    return bind


MODULE = build
