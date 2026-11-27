"""启动装配的命令声明与等待行为。"""

import asyncio

from ...declarations import CommandContext, builtin_commands


async def wait_until_cancelled() -> None:
    await asyncio.Event().wait()


async def dispatch(context: CommandContext) -> None:
    await wait_until_cancelled()


def plugin():
    return builtin_commands(__name__, {"run": dispatch})
