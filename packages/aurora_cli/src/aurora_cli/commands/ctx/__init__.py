"""ctx 命令声明与结果输出，实际状态操作由 core 完成。"""

from typing import TextIO

from aurora_core.ctx import StateAddress
from aurora_core.ids import Id
from aurora_core.invocation import invoke_operation
from aurora_core.json_data import encode_json

from ...declarations import CommandContext, builtin_commands


def address_data(address: StateAddress) -> dict[str, object]:
    return {"id": str(address.key), "location": dict(address.location)}


def write_json(output: TextIO, value: object) -> None:
    print(encode_json(value), file=output, flush=True)


def render_result(output: TextIO, name: str, result: object) -> None:
    if name == "ctx/list":
        if not isinstance(result, tuple) or any(not isinstance(item, StateAddress) for item in result):
            raise TypeError("ctx/list 必须返回状态地址元组")
        result = [address_data(item) for item in result]
    write_json(output, result)


async def list_states(context: CommandContext, **filters: object) -> None:
    result = await invoke_operation(context.registry, Id("org.aurora.core:operations/ctx/list"), **filters)
    render_result(context.output, "ctx/list", result)


async def watch_states(context: CommandContext, **filters: object) -> None:
    from .watch import watch

    await watch(context.registry, context.output, **filters)


def plugin():
    return builtin_commands(__name__, {"ctx/list": list_states, "ctx/watch": watch_states})
