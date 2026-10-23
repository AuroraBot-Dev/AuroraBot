"""将实例机制绑定成已有的 Operation；终端和 TUI 无需理解模块运行时类型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field, create_model

from playground.protocol import Empty, Model, Operation
from playground.workspace.records import Archive, Inspection, ReplayResult

if TYPE_CHECKING:
    from playground.workspace.runtime import Workspace


class Binding:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.spec = workspace.spec

    def input_type(self, name: str, base: type[Model], *, default: str | None = None) -> type[Model]:
        fields: dict[str, Any] = {
            self.spec.identity: (str, Field(default=default or self.spec.default_id, pattern=r"\S"))
        }
        return create_model(
            f"{self.workspace.module}_{name}",
            __base__=base,
            **fields,
        )

    def identity(self, arguments: dict[str, Any]) -> str:
        return arguments.pop(self.spec.identity)

    async def create(self, **arguments: Any) -> Model:
        instance_id = self.identity(arguments)
        return await self.workspace.create(arguments, instance_id)

    async def reset(self, **arguments: Any) -> Model:
        return await self.workspace.reset(self.identity(arguments), arguments["configuration"])

    async def export(self, **arguments: Any) -> Model:
        return await self.workspace.export(self.identity(arguments))

    async def replay(self, **arguments: Any) -> Model:
        return await self.workspace.replay(Archive.model_validate(arguments["archive"]), self.identity(arguments))

    async def close(self, **arguments: Any) -> Model:
        await self.workspace.dispose(self.identity(arguments))
        return Empty()

    async def inspect(self, **arguments: Any) -> Model:
        return await self.workspace.inspect(self.identity(arguments))

    def bind(self, operation: Operation) -> Operation:
        async def call(**arguments: Any) -> Model:
            return await self.workspace.call(self.identity(arguments), operation.name, arguments)

        return Operation(
            operation.name,
            operation.description,
            self.input_type(operation.name, operation.input_type),
            operation.output_type,
            call,
            operation.example,
            record=operation.record,
            replayable=operation.replayable,
        )

    def operations(self) -> tuple[Operation, ...]:
        target = self.input_type("target", Empty)
        fields: dict[str, Any] = {"configuration": (self.spec.configuration | None, None)}
        reset_type = create_model("Reset", __base__=target, **fields)
        result = [
            Operation(
                "create",
                "按配置创建独立实例。",
                self.input_type("create", self.spec.configuration),
                self.spec.snapshot.output_type,
                self.create,
                self.spec.example,
            ),
            *(self.bind(operation) for operation in self.workspace.operations.values()),
        ]
        if "inspect" not in self.workspace.operations:
            result.append(
                Operation(
                    "inspect", "查看配置、状态和无正文的调用摘要。", target, Inspection, self.inspect, {}, record=False
                )
            )
        result.extend(
            (
                Operation(
                    "reset",
                    "重新装配实例；省略 configuration 则沿用当前配置。",
                    reset_type,
                    self.spec.snapshot.output_type,
                    self.reset,
                    {},
                ),
                Operation(
                    "export",
                    "显式导出配置、操作和检查点；包含正文，请勿提交真实会话。",
                    target,
                    Archive,
                    self.export,
                    {},
                    record=False,
                ),
            )
        )
        if self.spec.isolated:
            result.append(self.replay_operation())
        result.append(Operation("close", "释放指定实例；其他实例不受影响。", target, Empty, self.close, {}))
        return tuple(result)

    def replay_operation(self) -> Operation:
        record_type = create_model(
            f"{self.workspace.module}_Record", __base__=Archive, configuration=(self.spec.configuration, ...)
        )
        replay_type = create_model(
            "Replay", __base__=self.input_type("replay", Empty, default="replay"), archive=(record_type, ...)
        )
        example = {
            "archive": {
                "module": self.workspace.module,
                "revision": self.spec.revision,
                "instance_id": self.spec.default_id,
                "configuration": self.spec.example,
                "initial": {},
                "checkpoints": [],
                "inspection": {},
            }
        }
        return Operation(
            "replay",
            "在隔离环境重跑允许复现的操作，并逐检查点比对。",
            replay_type,
            ReplayResult,
            self.replay,
            example,
        )
