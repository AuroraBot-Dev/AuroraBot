"""按显式组件依赖启动、停止并完成宿主最终落盘。"""

import asyncio
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from .ctx import Context
from .hooks import HookConnection, HookConnections, HookSlot
from .ids import Id
from .invocation import invoke_callable
from .persistence import ContextPersistence
from .registry import DefinitionRegistry, RegistryEntry
from .storage import StorageService

CONFIG = Id("org.aurora.core:lifecycle/config")
PREPARE = Id("org.aurora.core:lifecycle/prepare")
START = Id("org.aurora.core:lifecycle/start")
STOP = Id("org.aurora.core:lifecycle/stop")
CLEAN = Id("org.aurora.core:lifecycle/clean")
logger = logging.getLogger(__name__)


def install_lifecycle_slots(registry: DefinitionRegistry) -> None:
    """登记 config、prepare、start、stop、clean 五个无参数生命周期插槽。"""
    registry.register_many(
        RegistryEntry(
            identity, "hook_slot", HookSlot(), "aurora_core", register_to=Id("org.aurora.core:registries/hook_slots")
        )
        for identity in (CONFIG, PREPARE, START, STOP, CLEAN)
    )


@dataclass(frozen=True)
class LifecycleComponent:
    """实例依赖与入口关闭动作；五个阶段的处理器通过插槽连接提供。"""

    instance_id: str
    depends_on: tuple[str, ...] = ()
    stop_accepting: Callable[[], object] | None = None


def _ordered(components: Iterable[LifecycleComponent]) -> tuple[LifecycleComponent, ...]:
    entries: dict[str, LifecycleComponent] = {}
    for component in components:
        if not component.instance_id or component.instance_id in entries:
            raise ValueError("组件实例标识为空或重复")
        entries[component.instance_id] = component
    for component in entries.values():
        missing = set(component.depends_on) - entries.keys()
        if missing:
            raise ValueError(f"组件 {component.instance_id} 缺少依赖：{sorted(missing)}")
    ordered: list[LifecycleComponent] = []
    completed: set[str] = set()
    while entries:
        ready = next((item for item in entries.values() if set(item.depends_on) <= completed), None)
        if ready is None:
            raise ValueError("组件依赖存在环")
        ordered.append(ready)
        completed.add(ready.instance_id)
        del entries[ready.instance_id]
    return tuple(ordered)


class Lifecycle:
    """各阶段整体推进；依赖先 config/prepare/start，依赖者先 stop/clean。

    run 管理的工作由宿主收束，组件自行创建的任务由其 stop 处理器收束。
    全部 stop 完成后才 clean；收尾失败保留依赖及状态供重试，已完成处理器不重复执行。
    timeout 限制异步处理和等待，不抢占同步阻塞代码。
    """

    def __init__(
        self,
        ctx: Context,
        hooks: HookConnections,
        components: Iterable[LifecycleComponent],
        *,
        persistence: ContextPersistence | None = None,
        storage: StorageService | None = None,
        timeout: float = 10,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("生命周期超时必须为正有限数")
        self._components = _ordered(components)
        self._ctx = ctx
        self._hooks = hooks
        self._persistence = persistence
        self._storage = storage
        self._timeout = timeout
        self._state: Literal["new", "starting", "running", "stopping", "failed", "stopped"] = "new"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._attempted: set[str] = set()
        self._configured: set[str] = set()
        self._quiesced: set[str] = set()
        self._stopped: set[str] = set()
        self._cleaned: set[str] = set()
        self._finished_handlers: set[HookConnection] = set()
        self._work: set[asyncio.Task[object]] = set()
        self._stop_task: asyncio.Task[None] | None = None
        self._persistence_started = False

    @property
    def state(self) -> str:
        return self._state

    def _check_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("生命周期接口必须在启动它的宿主事件循环调用")

    async def _phase(self, phase: Id, component: LifecycleComponent) -> None:
        for connection in self._hooks.for_slot(phase, component.instance_id):
            if phase in (STOP, CLEAN) and connection in self._finished_handlers:
                continue
            async with asyncio.timeout(self._timeout):
                await self._hooks.invoke(connection)
            if phase in (STOP, CLEAN):
                self._finished_handlers.add(connection)

    async def start(self, *, configure: Callable[[], object] | None = None) -> None:
        """恢复状态后应用宿主配置，再 prepare/start；配置失败沿启动失败路径收尾。"""
        if self._state != "new":
            raise RuntimeError("生命周期只允许启动一次")
        self._loop = asyncio.get_running_loop()
        self._state = "starting"
        try:
            if self._persistence is not None:
                await self._persistence.start()
                self._persistence_started = True
            for component in self._components:
                self._configured.add(component.instance_id)
                await self._phase(CONFIG, component)
            if configure is not None:
                async with asyncio.timeout(self._timeout):
                    await invoke_callable(configure)
            for component in self._components:
                self._attempted.add(component.instance_id)
                await self._phase(PREPARE, component)
            for component in self._components:
                await self._phase(START, component)
        except BaseException as error:
            self._state = "failed"
            try:
                await self.stop()
            except BaseException as cleanup_error:  # noqa: BLE001 — 同时保留启动和收尾异常，包括取消。
                raise BaseExceptionGroup("启动失败且收尾未完成", [error, cleanup_error]) from None
            raise
        self._state = "running"

    async def run(self, target: Callable[..., object], *args: object, **kwargs: object) -> object:
        """仅运行期间接收工作；停止时等待已接收的工作，超时后请求取消。"""
        self._check_loop()
        if self._state != "running":
            raise RuntimeError("宿主未运行或已经停止接收新工作")
        task = asyncio.create_task(invoke_callable(target, *args, **kwargs))
        self._work.add(task)
        try:
            return await task
        finally:
            self._work.discard(task)

    async def _drain(self) -> None:
        if not self._work:
            return
        _, pending = await asyncio.wait(tuple(self._work), timeout=self._timeout)
        for task in pending:
            task.cancel()
        if pending:
            _, pending = await asyncio.wait(pending, timeout=self._timeout)
            if pending:
                raise TimeoutError("在途工作未完成取消，保留组件与存储供重试")

    async def _shutdown(self) -> None:
        try:
            components = [item for item in reversed(self._components) if item.instance_id in self._attempted]
            for component in components:
                if component.instance_id not in self._quiesced:
                    if component.stop_accepting is not None:
                        async with asyncio.timeout(self._timeout):
                            await invoke_callable(component.stop_accepting)
                    self._quiesced.add(component.instance_id)
            await self._drain()
            for component in components:
                if component.instance_id not in self._stopped:
                    await self._phase(STOP, component)
                    self._stopped.add(component.instance_id)
            for component in reversed(self._components):
                if component.instance_id in self._configured and component.instance_id not in self._cleaned:
                    await self._phase(CLEAN, component)
                    self._hooks.disconnect_instance(component.instance_id)
                    self._cleaned.add(component.instance_id)
            if self._persistence is not None and self._persistence_started:
                await self._persistence.close()
            self._hooks.close()
            if self._storage is not None:
                self._storage.close()
            self._ctx.close()
        except BaseException:
            self._state = "failed"
            raise
        self._state = "stopped"

    async def stop(self) -> None:
        """幂等停止；调用方取消等待不打断正在进行的收尾，可再次等待或重试。"""
        self._check_loop()
        if asyncio.current_task() in self._work:
            raise RuntimeError("在途工作不能等待自身停止")
        if asyncio.current_task() is self._stop_task:
            raise RuntimeError("停止处理器不能等待自身停止")
        if self._state == "starting":
            raise RuntimeError("启动期间请取消启动任务，由启动失败路径收尾")
        if self._state == "stopped":
            return
        if self._stop_task is None or self._stop_task.done():
            self._state = "stopping"
            self._stop_task = asyncio.create_task(self._shutdown(), name="aurora-lifecycle-stop")
            self._stop_task.add_done_callback(self._report_stop_failure)
        await asyncio.shield(self._stop_task)

    @staticmethod
    def _report_stop_failure(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("生命周期停止失败，资源保留供重试", exc_info=error)
