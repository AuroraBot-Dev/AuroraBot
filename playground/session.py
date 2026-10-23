"""逐行请求与响应；输入失败不执行模块，执行失败不自动重试。"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from playground.discovery import bind_operations, discover_modules
from playground.protocol import REQUEST, Call, Describe, Exit, ListModules, Model, Operation

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from aurora_kernel.discovery import DiscoverySource


def failure(code: str, message: str, details: object = None) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "details": details}}


def validation_failure(error: ValidationError) -> dict[str, Any]:
    return failure(
        "invalid_input",
        "输入不符合格式；请查询 describe 返回的 schema 和示例。",
        [{"path": list(item["loc"]), "type": item["type"]} for item in error.errors()],
    )


def reject_constant(value: str) -> None:
    raise ValueError(f"JSON 不支持 {value}")


def execute(
    request: Call, operation: Operation, resolve: Callable[[Model | Awaitable[Model]], Model]
) -> dict[str, Any]:
    try:
        arguments = operation.input_type.model_validate(request.input)
    except ValidationError as error:
        return validation_failure(error)
    try:
        result = resolve(operation.handler(**arguments.model_dump()))
        output = operation.output_type.model_validate(result).model_dump(mode="json")
    except (ValueError, TypeError, LookupError, RuntimeError) as error:
        return failure("execution_error", str(error), {"type": type(error).__name__})
    return {"ok": True, "module": request.module, "operation": operation.name, "result": output}


class Session:
    def __init__(self, sources: Iterable[DiscoverySource] | None = None) -> None:
        self.modules = discover_modules(sources)
        self._operations: dict[str, dict[str, Operation]] = {}
        self._runner: asyncio.Runner | None = None
        self.closed = False

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """退出、EOF 和中断共享清理路径；关闭会话所属的异步资源。"""
        self.closed = True
        if self._runner is not None:
            runner, self._runner = self._runner, None
            runner.close()

    def resolve(self, result: Model | Awaitable[Model]) -> Model:
        if isinstance(result, Model):
            return result
        if not inspect.isawaitable(result):
            raise TypeError("操作必须返回输出模型或可等待的输出模型")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            if inspect.iscoroutine(result):
                result.close()
            raise RuntimeError("同步 Playground 会话不能嵌套在运行中的事件循环内")
        if self._runner is None:
            self._runner = asyncio.Runner()
        return self._runner.run(await_result(result))

    def handle(self, line: str) -> dict[str, Any]:
        if self.closed:
            return failure("session_closed", "会话已结束。")
        try:
            payload = json.loads(line, parse_constant=reject_constant)
        except (ValueError, RecursionError):
            return failure("invalid_json", "请输入一行完整的 JSON 对象。")
        if isinstance(payload, dict):
            payload.setdefault("action", "call")
        try:
            request = REQUEST.validate_python(payload)
        except ValidationError as error:
            return validation_failure(error)
        if isinstance(request, Exit):
            self.close()
            return {"ok": True, "result": {"closed": True}}
        if isinstance(request, ListModules):
            return {
                "ok": True,
                "result": {
                    "modules": [
                        {"module": module.name, "description": module.description} for module in self.modules.values()
                    ],
                    "examples": [
                        *({"action": "describe", "module": name} for name in self.modules),
                        {"action": "exit"},
                    ],
                },
            }
        return self.dispatch(request)

    def dispatch(self, request: Call | Describe) -> dict[str, Any]:
        module = self.modules.get(request.module)
        if module is None:
            return failure("unknown_module", '模块不存在；使用 {"action":"list"} 查询。')
        try:
            available = self.operations(module.name)
        except (ValueError, TypeError) as error:
            return failure("invalid_module", str(error))
        operation = available.get(request.operation) if request.operation is not None else None
        if request.operation is not None and operation is None:
            return failure("unknown_operation", "操作不存在；使用 describe 查询该模块。")
        if isinstance(request, Describe):
            operations = (operation,) if operation is not None else tuple(available.values())
            return {
                "ok": True,
                "module": module.name,
                "result": {
                    "description": module.description,
                    "operations": [item.describe(module.name) for item in operations],
                },
            }
        assert operation is not None
        return execute(request, operation, self.resolve)

    def operations(self, module: str) -> dict[str, Operation]:
        if module not in self._operations:
            self._operations[module] = bind_operations(self.modules[module])
        return self._operations[module]


async def await_result(result: Awaitable[Model]) -> Model:
    return await result
