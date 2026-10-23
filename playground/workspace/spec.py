"""独立实例声明；复用操作协议与标准上下文管理器，不实现模块依赖或生命周期钩子。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager, AbstractContextManager

    from playground.protocol import Model, Operation


def project(value: Model) -> dict[str, Any]:
    return value.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    configuration: type[Model]
    open: Callable[[Model, str], AbstractContextManager[Any] | AbstractAsyncContextManager[Any]]
    snapshot: Operation
    operations: tuple[Operation, ...] = ()
    revision: str = "1"
    isolated: bool = False
    project: Callable[[Model], dict[str, Any]] = project
    identity: str = "instance_id"
    default_id: str = "default"
    implicit: bool = False
