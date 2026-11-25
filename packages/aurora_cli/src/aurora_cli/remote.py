"""将内置 ctx 命令传输至已有宿主，不构造本地 ctx 或存储。"""

import logging
from typing import TextIO

from aurora_api.access import token_from_env
from aurora_api.client import CtxClient
from aurora_core.ids import Id

from .commands.ctx import write_json

COMMANDS = {
    Id("org.aurora.cli:commands/ctx/get"): "get",
    Id("org.aurora.cli:commands/ctx/list"): "list",
    Id("org.aurora.cli:commands/ctx/set"): "set",
    Id("org.aurora.cli:commands/ctx/delete"): "delete",
    Id("org.aurora.cli:commands/ctx/watch"): "watch",
}


async def execute(
    url: str, identity: Id, values: dict[str, object], output: TextIO, *, token_env: str | None = None
) -> int:
    action = COMMANDS[identity]
    if "key" in values:
        values = {**values, "key": str(values["key"])}
    async with CtxClient(url, token=token_from_env(token_env)) as client:
        if action == "watch":
            async with client.watch(**values) as events:
                logging.getLogger(__name__).info("已连接 %s，正在观察 ctx 后续变化，Ctrl+C 退出", url)
                async for event in events:
                    write_json(output, event)
        else:
            write_json(output, await client.request(action, **values))
    return 0
