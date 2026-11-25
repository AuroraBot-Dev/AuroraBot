"""进程内单次调用，不承担组件流程控制。"""

import inspect
from collections.abc import Callable

from .ids import Id
from .registry import DefinitionRegistry


async def invoke_callable(target: Callable[..., object], /, *args: object, **kwargs: object) -> object:
    """同步函数在宿主线程执行，异步结果直接等待；异常与取消向调用方传播。

    超时由调用方通过 asyncio.timeout 等机制控制；同步阻塞函数不能被协程超时抢占。
    """
    result = target(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def invoke_operation(registry: DefinitionRegistry, identity: Id, /, *args: object, **kwargs: object) -> object:
    """按 ID 调用已登记 operation；可寻址资源和其他 kind 不视为操作。"""
    entry = registry.get(identity)
    if entry.kind != "operation" or not callable(entry.target):
        raise TypeError(f"目标不是可调用 operation：{identity}")
    return await invoke_callable(entry.target, *args, **kwargs)
