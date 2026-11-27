"""应用宿主拥有 ctx、连接、存储和生命周期，不解释命令或业务装配 ID。"""

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import install_context
from aurora_core.discovery import Plugin, load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService

from .assembly import AssemblyPlan, RuntimeGraph


class Host:
    def __init__(self, registry: DefinitionRegistry, data_dir: Path, *, workspace_root: Path) -> None:
        self.registry = registry
        self.ctx = install_context(registry)
        self.hooks = HookConnections(registry)
        try:
            self.storage = StorageService(data_dir)
        except BaseException:
            self.hooks.close()
            self.ctx.close()
            raise
        self.workspace_root = workspace_root
        self.graph = RuntimeGraph({}, ())
        self.lifecycle: Lifecycle | None = None

    @property
    def services(self) -> dict[str, Any]:
        return {
            "registry": self.registry,
            "ctx": self.ctx,
            "hooks": self.hooks,
            "storage": self.storage,
            "workspace_root": self.workspace_root,
        }

    @classmethod
    def create(cls, plan: AssemblyPlan, plugins: Iterable[Plugin], data_dir: Path, *, workspace_root: Path):
        registry = bootstrap()
        install_lifecycle_slots(registry)
        plugins = load_plugins(explicit=(item for item in plugins if item.name in plan.plugins), enabled=plan.plugins)
        register_plugins(registry, plugins)
        host = cls(registry, data_dir, workspace_root=workspace_root)
        try:
            host.assemble(plan, plugins)
        except BaseException:
            host.close()
            raise
        return host

    def assemble(self, plan: AssemblyPlan, plugins: Iterable[Plugin]) -> None:
        self.graph = plan.assemble(tuple(plugins), self.services)

    def mount(self, components: Iterable[LifecycleComponent]) -> None:
        """程序化应用显式交付已经构造和连接的组件，与文件装配共用生命周期。"""
        self.graph = RuntimeGraph(self.graph.instances, (*self.graph.components, *components), self.graph.connections)

    async def start(self, *, configure: Callable[[], object] | None = None) -> None:
        self.lifecycle = Lifecycle(
            self.ctx,
            self.hooks,
            self.graph.components,
            persistence=ContextPersistence(self.ctx, self.storage.snapshot_store()),
            storage=self.storage,
        )
        await self.lifecycle.start(configure=configure)

    async def run(self, function: Callable[..., object], *args: object, **kwargs: object) -> object:
        assert self.lifecycle is not None
        return await self.lifecycle.run(function, *args, **kwargs)

    async def stop(self) -> None:
        if self.lifecycle is None:
            self.close()
        else:
            await self.lifecycle.stop()

    def close(self) -> None:
        """构造或接线失败时释放尚未启动的宿主资源。"""
        self.hooks.close()
        self.storage.close()
        self.ctx.close()
