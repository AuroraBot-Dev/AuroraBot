"""Kernel 装配与观察适配；资源生命周期始终由真实 Host 管理。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

from aurora_kernel import Host, ModuleSpec, Namespace
from playground.protocol import Empty, Model, Operation
from playground.workspace import WorkspaceSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable


class Configuration(Model):
    modules: list[str] | None = Field(default=None, description="选择已声明模块；省略时选择全部，不自动补齐依赖")

    @model_validator(mode="after")
    def unique_modules(self) -> Configuration:
        if self.modules is not None and len(self.modules) != len(set(self.modules)):
            raise ValueError("模块选择不能重复")
        return self


class State(Model):
    revision: int
    namespaces: dict[str, dict[str, Any]]


class Call(Model):
    target: str = Field(pattern=r"\S")
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class Result(Model):
    value: Any


class Route(Model):
    target: str
    mode: str
    asynchronous: bool
    handlers: list[str]


class Inspection(Model):
    state: State
    modules: list[str]
    routes: list[Route]


def snapshot(host: Host) -> State:
    return State(revision=host.ctx.revision, namespaces=host.ctx.snapshot())


async def call(host: Host, *, target: str, args: list[Any], kwargs: dict[str, Any]) -> Result:
    return Result(value=await host.acall(target, *args, **kwargs))


def inspect(host: Host) -> Inspection:
    return Inspection(
        state=snapshot(host),
        modules=[spec.module_id for spec in host.resolution.construction],
        routes=[
            Route(
                target=target,
                mode=route.point.mode,
                asynchronous=route.asynchronous,
                handlers=[owner for owner, _hook in route.handlers],
            )
            for target, route in host.routes.items()
        ],
    )


def specification(
    declarations: Iterable[Namespace | ModuleSpec], *, isolated: bool = False, operations: tuple[Operation, ...] = ()
) -> WorkspaceSpec:
    """把自己的 namespace 声明注入同一工作台；自定义声明默认不允许复现。"""
    specs = tuple(item.spec if isinstance(item, Namespace) else item for item in declarations)
    available = {spec.module_id: spec for spec in specs}
    if len(available) != len(specs):
        raise ValueError("Kernel 工作台模块不能重名")

    @asynccontextmanager
    async def open_instance(configuration: Model, _instance_id: str) -> AsyncIterator[Host]:
        parsed = Configuration.model_validate(configuration)
        names = tuple(available) if parsed.modules is None else parsed.modules
        if set(names) - available.keys():
            raise ValueError("选择了未声明的 Kernel 模块")
        host = Host(available[name] for name in names)
        lifecycle = await host.prepare()
        try:
            yield host
        finally:
            await lifecycle.close()

    return WorkspaceSpec(
        configuration=Configuration,
        open=open_instance,
        snapshot=Operation("state", "读取 ctx 的结构化快照。", Empty, State, snapshot, {}, record=False),
        operations=(
            *operations,
            Operation(
                "call",
                "调用选定模块的真实调用点；参数按目标契约解释。",
                Call,
                Result,
                call,
                {"target": next((point.name for spec in specs for point in spec.points), "module:operation")},
                replayable=isolated,
            ),
            Operation("inspect", "观察实际模块选择、调用路由和 ctx。", Empty, Inspection, inspect, {}, record=False),
        ),
        isolated=isolated,
        implicit=True,
        example={"modules": list(available)},
    )
