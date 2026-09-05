"""操作资源树、参数和窄运行时端口契约。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class OperationScope(StrEnum):
    ALL = "all"


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


class EngineRuntimePort(Protocol):
    def engine_status(self) -> dict[str, Any]: ...


class ConfigRuntimePort(Protocol):
    def snapshot(self) -> dict[str, Any]: ...

    def read(self, name: str) -> dict[str, Any] | None: ...


class AgentsRuntimePort(Protocol):
    def agent_catalog(self) -> dict[str, Any]: ...

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None: ...


class ToolsRuntimePort(Protocol):
    def tool_catalog(self) -> dict[str, Any]: ...

    def tool_detail(self, tool_id: str) -> dict[str, Any] | None: ...


class PromptRuntimePort(Protocol):
    def prompt_catalog(self) -> dict[str, Any]: ...

    def prompt_detail(self, prompt_id: str) -> dict[str, Any] | None: ...


class AiRuntimePort(Protocol):
    def model_catalog(self) -> dict[str, Any]: ...

    def model_detail(self, endpoint_id: str) -> dict[str, Any] | None: ...


class WorldRuntimePort(Protocol):
    async def world_stream(self, *, after: int = 0, limit: int = 64) -> dict[str, Any]: ...

    async def world_commit(self, commit_id: str) -> dict[str, Any] | None: ...


class ConsoleRuntimePort(Protocol):
    def console_status(self) -> dict[str, Any]: ...


class UtilsRuntimePort(Protocol):
    def utils_status(self) -> dict[str, Any]: ...


class ContractsRuntimePort(Protocol):
    def contracts_status(self) -> dict[str, Any]: ...


class CadenceRuntimePort(Protocol):
    def cadence_status(self) -> dict[str, Any]: ...


class MemoryRuntimePort(Protocol):
    async def memory_snapshot(self) -> dict[str, Any]: ...


class McpRuntimePort(Protocol):
    def mcp_status(self) -> dict[str, Any]: ...

    def mcp_app(self, package: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class OpsPorts:
    engine: EngineRuntimePort | None
    config: ConfigRuntimePort
    agents: AgentsRuntimePort | None = None
    tools: ToolsRuntimePort | None = None
    prompt: PromptRuntimePort | None = None
    ai: AiRuntimePort | None = None
    world: WorldRuntimePort | None = None
    console: ConsoleRuntimePort | None = None
    utils: UtilsRuntimePort | None = None
    contracts: ContractsRuntimePort | None = None
    cadence: CadenceRuntimePort | None = None
    memory: MemoryRuntimePort | None = None
    mcp: McpRuntimePort | None = None


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
    def success(
        cls,
        data: dict[str, Any] | None = None,
        *,
        message: str | None = None,
    ) -> OperationResult:
        return cls(True, message=message, data=data)

    @classmethod
    def failure(cls, code: str, message: str) -> OperationResult:
        return cls(False, code=code, message=message, data=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "data": self.data,
        }


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
