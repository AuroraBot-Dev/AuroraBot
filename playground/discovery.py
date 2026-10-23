"""复用内核的包发现，验证 Playground 声明与名称冲突。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_kernel.discovery import PackageSource
from playground.protocol import Module, Operation
from playground.workspace.binding import Binding
from playground.workspace.spec import WorkspaceSpec

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora_kernel.discovery import DiscoverySource
    from playground.workspace.runtime import Workspace


def module_spec(source: object, origin: str) -> Module:
    candidate = getattr(source, "MODULE", source)
    if not isinstance(candidate, Module):
        raise TypeError(f"Playground 必须导出 Module 类型的 MODULE：{origin}")
    return candidate


def discover_modules(sources: Iterable[DiscoverySource] | None = None) -> dict[str, Module]:
    if sources is None:
        sources = (PackageSource("playground.modules", extract=module_spec, entry_module=None),)
    modules: dict[str, Module] = {}
    for source in sources:
        for candidate in source.discover():
            module = module_spec(candidate, type(source).__name__)
            if not module.name.strip():
                raise ValueError("Playground 名称必须非空")
            if (module.create is None) == (module.workspace is None):
                raise ValueError("Playground 必须且只能声明 create 或 workspace")
            if module.create is not None and not callable(module.create):
                raise ValueError("Playground create 必须可调用")
            if module.workspace is not None and not isinstance(module.workspace, WorkspaceSpec):
                raise TypeError("Playground workspace 必须是 WorkspaceSpec")
            if module.name in modules:
                raise ValueError(f"Playground 名称重复：{module.name}")
            modules[module.name] = module
    return modules


def bind_operations(module: Module, workspace: Workspace | None = None) -> dict[str, Operation]:
    operations: dict[str, Operation] = {}
    if workspace is not None:
        declarations = Binding(workspace).operations()
    else:
        if module.create is None:
            raise ValueError("实例模块需要绑定工作台")
        declarations = module.create()
    for operation in declarations:
        if not isinstance(operation, Operation) or not operation.name.strip() or not callable(operation.handler):
            raise ValueError(f"Playground 操作声明无效：{module.name}")
        if operation.name in operations:
            raise ValueError(f"Playground 操作重复：{module.name}:{operation.name}")
        operations[operation.name] = operation
    return operations
