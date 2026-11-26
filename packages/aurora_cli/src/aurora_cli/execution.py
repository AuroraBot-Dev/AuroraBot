"""统一调用命令绑定；普通操作的返回值以 JSON 输出。"""

from aurora_core.invocation import invoke_callable, invoke_operation
from aurora_core.json_data import encode_json

from .declarations import Command, CommandContext


async def execute_command(command: Command, context: CommandContext, values: dict[str, object]) -> int:
    if command.executor is not None:
        status = await invoke_callable(command.executor, context, **values)
        if status is None:
            return 0
        if type(status) is not int or not 0 <= status <= 255:
            raise TypeError("命令执行器必须返回 None 或 0 至 255 的整数退出码")
        return status
    if command.operation is None:
        raise ValueError("命令没有执行绑定")
    result = await invoke_operation(context.registry, command.operation, **values)
    print(encode_json(result), file=context.output, flush=True)
    return 0
