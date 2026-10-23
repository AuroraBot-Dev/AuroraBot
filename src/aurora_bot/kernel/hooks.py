from __future__ import annotations

from typing import Any

from aurora_bot.kernel.context import SERVICES
from aurora_kernel import Context, ModuleSpec, Namespace


def service_namespace(
    name: str,
    service: str,
    *,
    methods: tuple[str, ...] = (),
    asynchronous: tuple[str, ...] = (),
    attributes: tuple[str, ...] = (),
) -> Namespace:
    space = Namespace(ModuleSpec(f"aurora:kernel/module/{name}"))
    key = service
    for member in methods:
        space.callpoint(member)(_method(key, member))
    for member in asynchronous:
        space.callpoint(member)(_async_method(key, member))
    for member in attributes:
        space.callpoint(member)(_attribute(key, member))
    return space


def _method(key: str, name: str):
    def invoke(ctx: Context, *args: Any, **kwargs: Any) -> Any:
        return getattr(ctx[SERVICES][key], name)(*args, **kwargs)

    return invoke


def _async_method(key: str, name: str):
    async def invoke(ctx: Context, *args: Any, **kwargs: Any) -> Any:
        return await getattr(ctx[SERVICES][key], name)(*args, **kwargs)

    return invoke


def _attribute(key: str, name: str):
    def value(ctx: Context) -> Any:
        return getattr(ctx[SERVICES][key], name)

    return value
