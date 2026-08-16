"""操作注册表：装饰器收集、冲突校验与目录自描述。

操作以 ``@operation(...)`` 装饰器注册到模块级注册表；``iter_operations``
在首次调用时自动加载 ``ops.operations`` 下的全部子模块（显式导入，保证装饰器执行）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.contracts import OperationResult, OperationScope, OperationSpec, ParameterSpec

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_OPERATIONS: dict[str, OperationSpec] = {}
_ALIASES: dict[str, str] = {}
_LOADED = False


def operation(
    method: str,
    path: str,
    *,
    name: str,
    summary: str = "",
    parameters: tuple[ParameterSpec, ...] = (),
    aliases: tuple[str, ...] = (),
    scope: OperationScope = OperationScope.ALL,
) -> Callable[[Callable[..., Awaitable[OperationResult]]], Callable[..., Awaitable[OperationResult]]]:
    """装饰器：把处理器注册为资源树上的一个操作。"""

    def decorator(handler: Callable[..., Awaitable[OperationResult]]) -> Callable[..., Awaitable[OperationResult]]:
        spec = OperationSpec(
            method=method,
            path=path,
            name=name,
            summary=summary,
            parameters=parameters,
            aliases=aliases,
            scope=scope,
            handler=handler,
        )
        _register(spec)
        return handler

    return decorator


def _register(spec: OperationSpec) -> None:
    """注册操作并校验 path+method 唯一。"""
    key = f"{spec.method} {spec.path}"
    if key in _OPERATIONS:
        raise RuntimeError(f"duplicate operation registration: {key}")
    _OPERATIONS[key] = spec
    for alias in spec.aliases:
        if alias in _ALIASES:
            raise RuntimeError(f"duplicate command alias: {alias}")
        _ALIASES[alias] = key


def iter_operations() -> tuple[OperationSpec, ...]:
    """返回全部已注册操作（首次调用时加载子模块）。"""
    _load_all()
    return tuple(_OPERATIONS.values())


def find_by_alias(alias: str) -> OperationSpec | None:
    """按命令别名查找操作。"""
    _load_all()
    key = _ALIASES.get(alias)
    return _OPERATIONS.get(key) if key is not None else None


def catalog_entries() -> list[dict[str, Any]]:
    """操作目录自描述（/api/ops 与 /help 共用）。"""
    return [
        {
            "method": spec.method,
            "path": spec.path,
            "name": spec.name,
            "summary": spec.summary,
            "aliases": list(spec.aliases),
            "scope": spec.scope,
            "parameters": [
                {
                    "name": parameter.name,
                    "location": parameter.location,
                    "kind": parameter.kind,
                    "type": parameter.type,
                    "required": parameter.required,
                    "default": parameter.default,
                }
                for parameter in spec.parameters
            ],
        }
        for spec in iter_operations()
    ]


def _load_all() -> None:
    """显式导入全部操作子模块以触发注册。"""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from ops.operations import ai, apps, chat, config, console, engine, extensions, memory, system  # noqa: F401
