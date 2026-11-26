"""构造当前进程宿主并执行命令，收尾由 core 生命周期负责。"""

import inspect
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from aurora_config import configuration_component
from aurora_core.ctx import install_context
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import Lifecycle, LifecycleComponent
from aurora_core.persistence import ContextPersistence
from aurora_core.storage import StorageService

from .configuration import initialize_host_config
from .declarations import CONFIG, Command, CommandContext
from .execution import execute_command


async def execute(
    context: CommandContext,
    command: Command,
    values: dict[str, object],
    *,
    data_dir: Path,
    assembly: Id | None,
    config: object,
) -> int:
    """工厂接收 registry/ctx/hooks/storage/workspace_root，prepare/start 内初始化资源。"""
    registry = context.registry
    ctx = install_context(registry)
    lifecycle: Lifecycle | None = None
    try:
        factory = None
        if assembly is not None:
            entry = registry.get(assembly)
            if entry.kind != "assembly" or not callable(entry.target):
                raise TypeError(f"装配必须为可调用的 assembly：{assembly}")
            factory = entry.target
        storage = StorageService(data_dir)
        hooks = HookConnections(registry)
        try:
            initialize_host_config(storage.configuration_directory())
            components = (
                ()
                if factory is None
                else factory(registry=registry, ctx=ctx, hooks=hooks, storage=storage, workspace_root=context.root)
            )
            if inspect.iscoroutine(components):
                components.close()
                raise TypeError("装配工厂必须同步返回组件")
            if not isinstance(components, Iterable):
                raise TypeError("装配工厂必须返回 LifecycleComponent 可迭代对象")
            components = (configuration_component(registry, ctx, hooks, storage), *components)
            if any(not isinstance(component, LifecycleComponent) for component in components):
                raise TypeError("装配包含无效组件")
            lifecycle = Lifecycle(
                ctx, hooks, components, persistence=ContextPersistence(ctx, storage.snapshot_store()), storage=storage
            )
        except BaseException:
            hooks.close()
            storage.close()
            raise

        def configure() -> None:
            if config is not None:
                ctx.set(CONFIG, config)

        await lifecycle.start(configure=configure)
        try:
            return cast(int, await lifecycle.run(execute_command, command, context, values))
        finally:
            await lifecycle.stop()
    finally:
        if lifecycle is None:
            ctx.close()
