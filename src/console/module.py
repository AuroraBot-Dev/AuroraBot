"""``src.console`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.console import TerminalConsole
from src.contracts import FRONT_BINDINGS, Front, FrontContext, FrontIO, TerminalDispatcher, WorldWriter
from src.contracts import TerminalConsole as TerminalConsolePort
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio

    from src.contracts import FrontBinding


def _bind_console(console: TerminalConsolePort) -> FrontBinding:
    """把本地终端包装为交互式前台；所需能力由运行上下文按需提供。"""

    def bind(context: FrontContext) -> Front:
        dispatcher = context.get(TerminalDispatcher)
        io = context.get(FrontIO)

        async def run(stop: asyncio.Event) -> None:
            await console.run(dispatcher, stop_event=stop, readline=io.readline, output=io.output)

        return Front(run, interactive=True)

    return bind


@module(
    name="console",
    provides=TerminalConsolePort,
    requires=(WorldWriter,),
    contributes=(FRONT_BINDINGS,),
    declares=(FRONT_BINDINGS,),
)
def build(context: ModuleContext) -> TerminalConsolePort:
    console = TerminalConsole(context.get(WorldWriter))
    context.contribute(FRONT_BINDINGS, _bind_console(console))
    return console


MODULE = build
