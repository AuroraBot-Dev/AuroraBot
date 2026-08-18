"""操作资源树、参数和窄运行时端口契约。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class OperationScope(StrEnum):
    ALL = "all"
    TEXT_ONLY = "text_only"


class ParameterLocation(StrEnum):
    PATH = "path"
    QUERY = "query"
    BODY = "body"


class ParameterKind(StrEnum):
    POSITIONAL = "positional"
    NAMED = "named"
    FLAG = "flag"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    location: ParameterLocation
    kind: ParameterKind = ParameterKind.NAMED
    type: str = "str"
    required: bool = False
    default: Any = None
    help: str = ""


class TreeRuntimePort(Protocol):
    async def start_tree(self, message: str, *, tree_id: str | None = None) -> dict[str, Any]: ...

    def runtime_status(self) -> dict[str, Any]: ...

    def list_trees(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]: ...

    def tree_detail(self, tree_id: str) -> dict[str, Any] | None: ...

    def node_detail(self, tree_id: str, node_id: str) -> dict[str, Any] | None: ...


class ConfigRuntimePort(Protocol):
    def snapshot(self) -> dict[str, Any]: ...

    def read(self, name: str) -> dict[str, Any] | None: ...

    def set_app_enabled(self, package: str, *, enabled: bool) -> dict[str, Any]: ...

    def set_extension_enabled(self, extension_id: str, *, enabled: bool) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class OpsPorts:
    engine: TreeRuntimePort
    config: ConfigRuntimePort


@dataclass(frozen=True, slots=True)
class OperationContext:
    runtime: OpsPorts


@dataclass(frozen=True, slots=True)
class OperationResult:
    ok: bool
    code: str = "ok"
    message: str | None = None
    data: dict[str, Any] | None = field(default_factory=dict)

    @classmethod
    def success(cls, data: dict[str, Any] | None = None, *, message: str | None = None) -> OperationResult:
        return cls(True, message=message, data=data)

    @classmethod
    def failure(cls, code: str, message: str) -> OperationResult:
        return cls(False, code=code, message=message, data=None)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "code": self.code, "message": self.message, "data": self.data}


type OperationHandler = Callable[[OperationContext, dict[str, Any]], Awaitable[OperationResult]]


@dataclass(frozen=True, slots=True)
class OperationSpec:
    method: str
    path: str
    name: str
    summary: str = ""
    parameters: tuple[ParameterSpec, ...] = ()
    aliases: tuple[str, ...] = ()
    scope: OperationScope = OperationScope.ALL
    handler: OperationHandler | None = None

    def parameter(self, name: str) -> ParameterSpec | None:
        return next((parameter for parameter in self.parameters if parameter.name == name), None)
