from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

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


@dataclass(frozen=True, slots=True)
class CallRoute:
    point: Callpoint
    handlers: tuple[tuple[str, Hook], ...]

    @property
    def asynchronous(self) -> bool:
        return any(
            inspect.iscoroutinefunction(inspect.unwrap(hook.callback))
            or inspect.iscoroutinefunction(type(hook.callback).__call__)
            for _, hook in self.handlers
        )

    def result(self, values: list[Any]) -> Any:
        if self.point.mode == "single":
            return values[0]
        return tuple(values) if self.point.mode == "collect" else None


class Calls:
    def __init__(self, specs: Iterable[ModuleSpec]) -> None:
        points: dict[str, Callpoint] = {}
        handlers: dict[str, list[tuple[str, Hook]]] = {}
        for spec in specs:
            for point in spec.points:
                if not point.name.startswith(f"{spec.module_id}:"):
                    raise ValueError(f"调用点必须属于声明模块：{point.name}")
                if point.name in points:
                    raise ValueError(f"调用点重复声明：{point.name}")
                points[point.name] = point
            for hook in spec.handlers:
                handlers.setdefault(hook.target, []).append((spec.module_id, hook))
        for target in handlers:
            if target not in points:
                raise ValueError(f"调用点尚未声明：{target}")
        self.routes: Mapping[str, CallRoute] = MappingProxyType(
            {target: self._select(point, handlers.get(target, [])) for target, point in points.items()}
        )

    @staticmethod
    def _select(point: Callpoint, handlers: list[tuple[str, Hook]]) -> CallRoute:
        ordered = sorted(handlers, key=lambda item: -item[1].priority)
        if point.mode == "single":
            if not ordered:
                raise ValueError(f"调用点没有实现：{point.name}")
            if len(ordered) > 1 and ordered[0][1].priority == ordered[1][1].priority:
                raise ValueError(f"调用点存在同优先级实现：{point.name}")
            ordered = ordered[:1]
        return CallRoute(point, tuple(ordered))

    def call(self, ctx: Context, target: str, *args: Any, **kwargs: Any) -> Any:
        route = self._route(target)
        if route.asynchronous:
            raise TypeError(f"调用点包含异步实现，请使用 acall：{target}")
        return route.result([invoke_sync(ctx, owner, hook.callback, *args, **kwargs) for owner, hook in route.handlers])

    async def acall(self, ctx: Context, target: str, *args: Any, **kwargs: Any) -> Any:
        route = self._route(target)
        results = []
        for owner, hook in route.handlers:
            results.append(await invoke(ctx, owner, hook.callback, *args, **kwargs))
        return route.result(results)

    def _route(self, target: str) -> CallRoute:
        try:
            return self.routes[target]
        except KeyError as error:
            raise LookupError(f"调用点不存在：{target}") from error
