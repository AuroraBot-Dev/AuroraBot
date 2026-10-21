"""调用点的冻结路由；直接传普通参数，保留异常与取消语义。"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora_kernel.context import Context
    from aurora_kernel.declaration import Callpoint, Hook, ModuleSpec


def invoke_sync(ctx: Context, source: str, callback: Callable, *args: Any, **kwargs: Any) -> Any:
    with ctx.bind(source):
        result = callback(ctx, *args, **kwargs)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError(f"同步调用不能执行异步函数：{source}；请使用异步调用入口")
        return result


async def invoke(ctx: Context, source: str, callback: Callable, *args: Any, **kwargs: Any) -> Any:
    with ctx.bind(source):
        result = callback(ctx, *args, **kwargs)
        return await result if inspect.isawaitable(result) else result


class Calls:
    """构建前裁决重复声明、缺失调用点和单实现冲突。"""

    def __init__(self, specs: Iterable[ModuleSpec]) -> None:
        self._points: dict[str, Callpoint] = {}
        self._handlers: dict[str, list[tuple[str, Hook]]] = {}
        specs = tuple(specs)
        for spec in specs:
            for point in spec.points:
                if not point.name.startswith(f"{spec.module_id}:"):
                    raise ValueError(f"调用点必须属于声明模块：{point.name}")
                if point.name in self._points:
                    raise ValueError(f"调用点重复声明：{point.name}")
                self._points[point.name] = point
            for handler in spec.handlers:
                self._handlers.setdefault(handler.target, []).append((spec.module_id, handler))
        for target in self._handlers:
            if target not in self._points:
                raise ValueError(f"调用点尚未声明：{target}")
        self._select()

    def _select(self) -> None:
        for target, point in self._points.items():
            handlers = self._handlers.get(target, [])
            handlers.sort(key=lambda item: -item[1].priority)
            if point.mode == "single":
                if not handlers:
                    raise ValueError(f"调用点没有实现：{target}")
                if len(handlers) > 1 and handlers[0][1].priority == handlers[1][1].priority:
                    raise ValueError(f"调用点存在同优先级实现：{target}")
                handlers = handlers[:1]
            self._handlers[target] = handlers

    def call(self, ctx: Context, target: str, *args: Any, **kwargs: Any) -> Any:
        point = self._point(target)
        # 在任何实现执行前拒绝异步路由，避免执行到一半才发现调用方式错误。
        if any(inspect.iscoroutinefunction(hook.callback) for _, hook in self._handlers[target]):
            raise TypeError(f"调用点包含异步实现，请使用 acall：{target}")
        results = [invoke_sync(ctx, owner, hook.callback, *args, **kwargs) for owner, hook in self._handlers[target]]
        return self._result(point, results)

    async def acall(self, ctx: Context, target: str, *args: Any, **kwargs: Any) -> Any:
        point = self._point(target)
        results = []
        for owner, hook in self._handlers[target]:
            results.append(await invoke(ctx, owner, hook.callback, *args, **kwargs))
        return self._result(point, results)

    def _point(self, target: str) -> Callpoint:
        try:
            return self._points[target]
        except KeyError as error:
            raise LookupError(f"调用点不存在：{target}") from error

    @staticmethod
    def _result(point: Callpoint, results: list[Any]) -> Any:
        if point.mode == "single":
            return results[0]
        return tuple(results) if point.mode == "collect" else None
