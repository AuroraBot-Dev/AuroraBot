"""交互协议和操作说明；只在 playground 边界适配 JSON，不改变模块契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from playground.workspace.spec import WorkspaceSpec


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Empty(Model):
    pass


class Call(Model):
    action: Literal["call"] = "call"
    module: str
    operation: str
    input: dict[str, Any] = Field(default_factory=dict)


class Describe(Model):
    action: Literal["describe"]
    module: str
    operation: str | None = None


class ListModules(Model):
    action: Literal["list"]


class Exit(Model):
    action: Literal["exit"]


REQUEST = TypeAdapter(Annotated[Call | Describe | ListModules | Exit, Field(discriminator="action")])


@dataclass(frozen=True, slots=True)
class Operation:
    name: str
    description: str
    input_type: type[Model]
    output_type: type[Model]
    handler: Callable[..., Model | Awaitable[Model]]
    example: dict[str, Any]
    record: bool = True
    replayable: bool = False

    def describe(self, module: str) -> dict[str, Any]:
        return {
            "operation": self.name,
            "description": self.description,
            "input_schema": self.input_type.model_json_schema(),
            "output_schema": self.output_type.model_json_schema(),
            "example": {"module": module, "operation": self.name, "input": self.example},
            "record": self.record,
            "replayable": self.replayable,
        }


@dataclass(frozen=True, slots=True)
class Module:
    """声明独立工作台，或直接绑定无实例的操作；发现时不获取运行资源。"""

    name: str
    description: str
    create: Callable[[], tuple[Operation, ...]] | None = None
    workspace: WorkspaceSpec | None = None
