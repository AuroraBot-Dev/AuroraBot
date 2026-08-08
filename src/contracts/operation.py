"""操作体系契约：RESTful 资源树与文本命令同构（RFC 0218）。

同一 ``OperationSpec`` 同时表达 REST 端点（method + path + location 参数）
与斜杠命令（别名 + positional/命名参数），双入口解析出同一 ``params``，
并返回同一 ``OperationResult`` JSON envelope。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.contracts.event import RuntimeInput
    from src.contracts.ports import PanelRuntime


class OperationScope(StrEnum):
    """操作可被哪些入口触发。"""

    ALL = "all"
    CONSOLE_ONLY = "console_only"


class ParameterLocation(StrEnum):
    """参数在 REST 请求中的位置；文本入口相应映射。"""

    PATH = "path"
    QUERY = "query"
    BODY = "body"


class ParameterKind(StrEnum):
    """参数在文本命令中的解析形态。"""

    POSITIONAL = "positional"
    NAMED = "named"
    FLAG = "flag"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """操作的单一参数声明：REST 与文本共用的解析依据。"""

    name: str
    location: ParameterLocation
    kind: ParameterKind = ParameterKind.NAMED
    type: str = "str"
    required: bool = False
    default: Any = None
    help: str = ""


OperationHandler = Callable[["OperationContext", dict[str, Any]], Awaitable["OperationResult"]]


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """资源树上的一个操作：REST 路由与命令文本共享此声明。"""

    method: str
    path: str
    name: str
    summary: str = ""
    parameters: tuple[ParameterSpec, ...] = ()
    aliases: tuple[str, ...] = ()
    scope: OperationScope = OperationScope.ALL
    handler: OperationHandler | None = None

    def parameter(self, name: str) -> ParameterSpec | None:
        """按参数名查找声明。"""
        return next((p for p in self.parameters if p.name == name), None)


@dataclass(frozen=True, slots=True)
class OperationResult:
    """操作的双入口唯一输出，序列化为固定 JSON envelope。"""

    ok: bool
    code: str = "ok"
    message: str | None = None
    data: dict[str, Any] | None = field(default_factory=dict)

    @classmethod
    def success(cls, data: dict[str, Any] | None = None, *, message: str | None = None) -> OperationResult:
        """构造成功结果。"""
        return cls(ok=True, code="ok", message=message, data=data)

    @classmethod
    def failure(cls, code: str, message: str | None = None) -> OperationResult:
        """构造业务失败结果（仍以 HTTP 200 返回）。"""
        return cls(ok=False, code=code, message=message, data=None)

    def to_dict(self) -> dict[str, Any]:
        """序列化为固定 envelope。"""
        return {"ok": self.ok, "code": self.code, "message": self.message, "data": self.data}


@dataclass(frozen=True, slots=True)
class OperationContext:
    """操作处理器使用的运行时与请求上下文。"""

    runtime: "PanelRuntime"
    request: "RuntimeInput | None" = None
