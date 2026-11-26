"""启动装配的命令声明与等待行为。"""

import asyncio

from ...declarations import CommandContext, command_plugin

DEFINITIONS = {"run": {"help": "启动选定装配，Ctrl+C 停止", "arguments": [{"name": "assembly", "type": "id"}]}}


async def wait_until_cancelled() -> None:
    await asyncio.Event().wait()


async def dispatch(context: CommandContext) -> None:
    await wait_until_cancelled()


def plugin():
    return command_plugin(
        __name__,
        {"run": {**DEFINITIONS["run"], "executor": dispatch, "runtime": True, "assembly_argument": "assembly"}},
    )
