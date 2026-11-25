"""ctx 命令声明与结果输出，实际状态操作由 core 完成。"""

from typing import TextIO

from aurora_core.ctx import StateAddress
from aurora_core.ids import Id
from aurora_core.invocation import invoke_operation
from aurora_core.json_data import encode_json

from ...declarations import CommandContext, command_plugin

KEY = {"name": "key", "type": "id"}
WHERE = {"name": "location", "type": "location", "option": True}
DEFINITIONS = {
    "ctx/get": {"help": "读取精确状态地址", "arguments": [KEY, WHERE]},
    "ctx/set": {"help": "以 JSON 整项替换状态", "arguments": [KEY, {"name": "value", "type": "json"}, WHERE]},
    "ctx/delete": {"help": "删除精确状态地址", "arguments": [KEY, WHERE]},
    "ctx/list": {"help": "枚举已赋值地址", "arguments": [{**KEY, "option": True}, WHERE]},
    "ctx/watch": {"help": "观察当前宿主后续变化，Ctrl+C 退出", "arguments": [{**KEY, "option": True}, WHERE]},
}
for name, spec in DEFINITIONS.items():
    if name != "ctx/watch":
        spec["operation"] = f"org.aurora.core:operations/{name}"


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
    definitions = {name: dict(spec) for name, spec in DEFINITIONS.items()}
    definitions["ctx/list"].pop("operation")
    definitions["ctx/list"].update(executor=list_states, runtime=True)
    definitions["ctx/watch"].update(executor=watch_states, runtime=True)
    return command_plugin(__name__, definitions)
