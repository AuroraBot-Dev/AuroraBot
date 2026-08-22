"""操作装饰器注册表与目录自描述。"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ops.contracts import OperationResult, OperationScope, OperationSpec, ParameterSpec

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_OPERATIONS: dict[str, OperationSpec] = {}
_ALIASES: dict[str, str] = {}


@dataclass(slots=True)
class _RegistryState:
    loaded: bool = False


_STATE = _RegistryState()


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
    def decorator(handler: Callable[..., Awaitable[OperationResult]]) -> Callable[..., Awaitable[OperationResult]]:
        _register(OperationSpec(method.upper(), path, name, summary, parameters, aliases, scope, handler))
        return handler

    return decorator


def _register(spec: OperationSpec) -> None:
    key = f"{spec.method} {spec.path}"
    if key in _OPERATIONS:
        raise RuntimeError(f"操作重复注册：{key}")
    _OPERATIONS[key] = spec
    for alias in spec.aliases:
        if alias in _ALIASES:
            raise RuntimeError(f"操作别名重复注册：{alias}")
        _ALIASES[alias] = key


def iter_operations() -> tuple[OperationSpec, ...]:
    _load_all()
    return tuple(_OPERATIONS.values())


def find_by_alias(alias: str) -> OperationSpec | None:
    _load_all()
    key = _ALIASES.get(alias)
    return _OPERATIONS.get(key) if key is not None else None


def catalog_entries() -> list[dict[str, Any]]:
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
    if _STATE.loaded:
        return
    _STATE.loaded = True
    for module in (
        "ops.operations.config",
        "ops.operations.engine",
        "ops.operations.system",
        "ops.operations.agents",
        "ops.operations.tools",
        "ops.operations.prompt",
        "ops.operations.ai",
        "ops.operations.world",
        "ops.operations.console",
        "ops.operations.utils",
        "ops.operations.contracts",
        "ops.operations.cadence",
        "ops.operations.memory",
    ):
        importlib.import_module(module)
