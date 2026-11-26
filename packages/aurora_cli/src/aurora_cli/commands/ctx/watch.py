"""ctx 后续变化的订阅、JSON 输出与取消。"""

import asyncio
from typing import TextIO

from aurora_core.ctx import StateChange
from aurora_core.ids import Id
from aurora_core.invocation import invoke_operation
from aurora_core.registry import DefinitionRegistry

from . import address_data, write_json


async def watch(registry: DefinitionRegistry, output: TextIO, **filters: object) -> None:
    """订阅当前宿主中的后续变化；取消或输出失败时释放订阅。"""
    changes: asyncio.Queue[StateChange] = asyncio.Queue()
    handle = await invoke_operation(
        registry, Id("org.aurora.core:operations/ctx/subscribe"), changes.put_nowait, **filters
    )
    try:
        while True:
            change = await changes.get()
            write_json(
                output,
                {
                    **address_data(change.address),
                    "revision": change.revision,
                    "action": change.action,
                    "value": change.value,
                    "previous": change.previous,
                    "existed": change.existed,
                },
            )
    finally:
        await invoke_operation(registry, Id("org.aurora.core:operations/ctx/unsubscribe"), handle)
