"""来源工厂登记、固定身份的接纳入口及宿主生命周期绑定。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from threading import get_ident
from typing import Protocol

from aurora_core import entry_from, hook_handler
from aurora_core.bootstrap import Receiver
from aurora_core.ctx import Context, StateChange
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.json_data import encode_json
from aurora_core.lifecycle import CLEAN, PREPARE, START, STOP, LifecycleComponent
from aurora_core.registry import RegistryEntry

from .records import Presentation, WorldReceipt, WorldRecords, _identity

SOURCES = Id("org.aurora.world:registries/sources")
SOURCE_STATUS = Id("org.aurora.world:state/sources")
logger = logging.getLogger(__name__)


def validate_source_status(value: object) -> None:
    """运行观察值只包含 JSON；状态不进入业务快照。"""
    encode_json(value)


class SourceUnavailableError(RuntimeError):
    """来源尚未开放或已停止接纳，消息未写入记录。"""


class SourceEmit(Protocol):
    """只在宿主线程同步提交；来源身份由装配绑定，回执表示 world 已接纳。"""

    def __call__(self, *, message_id: str, payload: object) -> WorldReceipt: ...


@dataclass(frozen=True)
class SourceInstance:
    """来源的异步生命周期动作；start 返回表示启动完成，不等待来源整个寿命。

    可选 run 主循环由所有者监督；stop 结束其余自有任务，aclose 释放资源。
    停止和释放失败后须能再次调用，run 退出后不自动重启。
    工厂返回前的失败和取消由工厂清理，返回后资源交给 WorldSources 托管。
    on_context_change 同步响应有效状态变化，须自行合并重复更新；停止接纳后不再通知。
    """

    start: Callable[[], Awaitable[None]]
    stop: Callable[[], Awaitable[None]]
    aclose: Callable[[], Awaitable[None]]
    run: Callable[[], Awaitable[None]] | None = None
    on_context_change: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        if not all(callable(action) for action in (self.start, self.stop, self.aclose)):
            raise TypeError("来源实例必须提供可调用的 start/stop/aclose")
        if self.run is not None and not callable(self.run):
            raise TypeError("来源主循环必须可调用")
        if self.on_context_change is not None and not callable(self.on_context_change):
            raise TypeError("来源上下文通知必须可调用")


class SourceFactory(Protocol):
    """prepare 阶段创建来源；不接收原始 ctx，运行时共享资源通过装配注入。"""

    async def __call__(self, *, source_id: str, emit: SourceEmit, config: dict[str, object]) -> SourceInstance: ...


@dataclass(frozen=True)
class SourceSpec:
    """来源定义；登记与接入诊断只检查声明，不调用工厂。"""

    factory: SourceFactory

    def __post_init__(self) -> None:
        if not callable(self.factory):
            raise TypeError("来源工厂必须可调用")


class SourceReceiver:
    def rejection_reason(self, entry: RegistryEntry) -> str | None:
        return None if entry.kind == "source" and isinstance(entry.target, SourceSpec) else "来源登记需要 SourceSpec"


@dataclass
class _Binding:
    source_id: str
    definition_id: Id
    factory: SourceFactory
    config: dict[str, object]
    instance: SourceInstance | None = None
    accepting: bool = False
    started: bool = False
    stopped: bool = False
    stop_completed: bool = False
    cancel_requested: bool = False
    task: asyncio.Task[None] | None = None
    observed: bool = False
    status: str | None = None
    error: str | None = None


class WorldSources:
    """一个宿主的来源所有者；同一 ctx 的来源应由同一对象装配。

    add 选择定义并绑定唯一 source_id；component 只连接现有生命周期插槽。
    进入各来源 start 时开放其入口，启动失败立即关闭全部入口；已接纳记录不撤销。
    stop_accepting 永久封闭入口，不因重试清理而重新开放；重新启动需新建宿主所有者。
    插件内代码并非安全隔离，固定回调只约束正常接口使用，不阻止恶意 Python 反射。
    """

    def __init__(
        self, ctx: Context, hooks: HookConnections, records: WorldRecords, *, instance_id: str = "aurora_world/sources"
    ) -> None:
        _identity(instance_id)
        self._ctx, self._hooks = ctx, hooks
        self.records = records
        self._instance_id = instance_id
        self._owner = get_ident()
        self._bindings: dict[str, _Binding] = {}
        self._connected = False
        self._prepare_called = False
        self._prepared = False
        self._start_called = False
        self._quiesced = False
        self._context_subscription: str | None = None

    def _check_owner(self) -> None:
        if get_ident() != self._owner:
            raise RuntimeError("来源接口必须在创建它的宿主线程调用")

    def add(
        self,
        identity: Id,
        *,
        source_id: str,
        config: dict[str, object] | None = None,
        factory: SourceFactory | None = None,
        presentation: Presentation | None = None,
    ) -> None:
        """准备前选择一个来源；source_id 在本所有者内唯一，配置必须为 JSON 对象。"""
        self._check_owner()
        if self._prepare_called or self._quiesced:
            raise RuntimeError("来源已经开始准备或停止，不接受新的装配")
        _identity(source_id)
        if source_id in self._bindings:
            raise ValueError("来源实例身份重复")
        receiver = self._ctx.registry.get(SOURCES)
        if receiver.kind != "registry" or not isinstance(receiver.target, Receiver):
            raise ValueError("未登记 world 来源接收方")
        entry = self._ctx.registry.get(identity)
        if entry.register_to != SOURCES or entry.kind != "source" or not isinstance(entry.target, SourceSpec):
            raise ValueError("目标不是已登记的世界来源")
        reason = receiver.target.rejection_reason(entry)
        if reason is not None:
            raise ValueError(f"来源接入被拒绝：{reason}")
        values = {} if config is None else config
        if type(values) is not dict:
            raise TypeError("来源配置必须为 JSON 对象")
        encode_json(values)
        if factory is not None and not callable(factory):
            raise TypeError("来源实例工厂必须可调用")
        selected = presentation or {
            "org.aurora.world:sources/environment/time": "time",
            "org.aurora.world:sources/environment/weather": "weather",
        }.get(str(identity), "events")
        self.records.select(source_id, selected)
        self._bindings[source_id] = _Binding(
            source_id, identity, entry.target.factory if factory is None else factory, deepcopy(values)
        )

    def component(self, *, depends_on: tuple[str, ...] = ()) -> LifecycleComponent:
        """连接来源所有者的生命周期；不创建来源、任务或状态。"""
        self._check_owner()
        if self._connected or self._prepare_called or self._quiesced:
            raise RuntimeError("来源生命周期已连接或不再允许装配")
        links = []
        try:
            for phase, method in ((PREPARE, self.prepare), (START, self.start), (STOP, self.stop), (CLEAN, self.clean)):
                entry = entry_from(method, provider="aurora_world")
                links.append(
                    self._hooks.connect(
                        phase,
                        entry.id,
                        slot_instance=self._instance_id,
                        handler_instance=self._instance_id,
                        target=method,
                    )
                )
        except Exception:
            for link in links:
                self._hooks.disconnect(link)
            raise
        self._connected = True
        return LifecycleComponent(self._instance_id, depends_on=depends_on, stop_accepting=self.stop_accepting)

    def _emit(self, binding: _Binding, *, message_id: str, payload: object) -> WorldReceipt:
        self._check_owner()
        self._observe_task(binding)
        if not binding.accepting or self._quiesced:
            raise SourceUnavailableError("来源尚未启动或已经停止接纳")
        return self.records.append(source_id=binding.source_id, message_id=message_id, payload=payload)

    def _publish(self, binding: _Binding, status: str | None = None) -> None:
        if status is not None:
            binding.status = status
        if binding.status is not None:
            self._ctx.set(
                SOURCE_STATUS,
                {
                    "definition_id": str(binding.definition_id),
                    "status": binding.status,
                    "accepting": binding.accepting,
                    "error": binding.error,
                },
                location={"source_id": binding.source_id},
            )

    def _fail(self, binding: _Binding, code: str) -> None:
        binding.accepting = False
        binding.error = code
        self._publish(binding, "failed")
        logger.error("世界来源失败：source_id=%s code=%s", binding.source_id, code)

    def _observe_task(self, binding: _Binding, task: asyncio.Task[None] | None = None) -> None:
        task = binding.task
        if task is None or not task.done() or binding.observed:
            return
        binding.observed = True
        binding.accepting = False
        if binding.error == "context_update_failed":
            if not task.cancelled():
                task.exception()
            return
        if task.cancelled():
            if not self._quiesced:
                self._fail(binding, "background_cancelled")
        else:
            error = task.exception()
            if error is not None and not (self._quiesced and isinstance(error, SourceUnavailableError)):
                self._fail(binding, "background_failed")
            elif not self._quiesced:
                self._publish(binding, "completed")

    async def _run(self, binding: _Binding) -> None:
        assert binding.instance is not None and binding.instance.run is not None
        await binding.instance.run()

    @hook_handler("org.aurora.world:handlers/sources/prepare", slot=PREPARE)
    async def prepare(self) -> None:
        self._check_owner()
        if self._prepare_called or self._quiesced:
            raise RuntimeError("来源不能重复准备或在停止后准备")
        self._prepare_called = True
        binding = None
        try:
            for binding in self._bindings.values():
                self._publish(binding, "preparing")
                instance = await binding.factory(
                    source_id=binding.source_id, emit=partial(self._emit, binding), config=deepcopy(binding.config)
                )
                if not isinstance(instance, SourceInstance):
                    raise TypeError("来源工厂必须返回 SourceInstance")
                binding.instance = instance
                if self._quiesced:
                    raise SourceUnavailableError("来源准备期间已停止接纳")
                self._publish(binding, "prepared")
            self.records.refresh()
        except BaseException:
            if binding is not None:
                self._fail(binding, "prepare_failed")
            self.stop_accepting()
            raise
        self._prepared = True

    @hook_handler("org.aurora.world:handlers/sources/start", slot=START)
    async def start(self) -> None:
        self._check_owner()
        if not self._prepared or self._start_called or self._quiesced:
            raise RuntimeError("来源尚未准备、已经启动或已经停止")
        self._start_called = True
        try:
            for binding in self._bindings.values():
                if self._quiesced:
                    raise SourceUnavailableError("来源启动期间已停止接纳")
                assert binding.instance is not None
                binding.accepting = binding.started = True
                self._publish(binding, "starting")
                await binding.instance.start()
                if self._quiesced:
                    raise SourceUnavailableError("来源启动期间已停止接纳")
                self._publish(binding, "running")
                if binding.instance.run is not None:
                    binding.task = asyncio.create_task(self._run(binding), name=f"world-source:{binding.source_id}")
                    binding.task.add_done_callback(partial(self._observe_task, binding))
            if any(binding.instance and binding.instance.on_context_change for binding in self._bindings.values()):
                self._context_subscription = self._ctx.subscribe(self._context_changed)
        except BaseException:
            self._fail(binding, "start_failed")
            self.stop_accepting()
            raise

    def _context_changed(self, change: StateChange) -> None:
        """通知有效 ctx 变化；来源可写回状态，须自行使反馈收敛。"""
        if self._quiesced or (change.existed and change.action == "set" and change.value == change.previous):
            return
        for binding in self._bindings.values():
            if binding.accepting and binding.instance and binding.instance.on_context_change:
                try:
                    binding.instance.on_context_change()
                except Exception:  # noqa: BLE001 - 旁路刷新失败归属来源，不撤销已提交的 ctx 变更。
                    binding.accepting = False
                    self._fail(binding, "context_update_failed")
                    if binding.task is not None:
                        binding.task.cancel()

    def stop_accepting(self) -> None:
        """同步且幂等封闭所有入口，包括来源已保留的回调。"""
        self._check_owner()
        self._quiesced = True
        if self._context_subscription is not None:
            self._ctx.unsubscribe(self._context_subscription)
            self._context_subscription = None
        for binding in self._bindings.values():
            if binding.accepting:
                binding.accepting = False
                self._publish(binding)

    @hook_handler("org.aurora.world:handlers/sources/stop", slot=STOP)
    async def stop(self) -> None:
        self.stop_accepting()
        for binding in reversed(tuple(self._bindings.values())):
            if binding.instance is not None and binding.started and not binding.stopped:
                self._publish(binding, "stopping")
                try:
                    if not binding.stop_completed:
                        await binding.instance.stop()
                        binding.stop_completed = True
                finally:
                    if binding.task is not None and not binding.task.done() and not binding.cancel_requested:
                        binding.cancel_requested = True
                        binding.task.cancel()
                if binding.task is not None:
                    await asyncio.wait({binding.task})
                    self._observe_task(binding)
                binding.stopped = True
                self._publish(binding, "stopped")

    @hook_handler("org.aurora.world:handlers/sources/clean", slot=CLEAN)
    async def clean(self) -> None:
        self.stop_accepting()
        for binding in reversed(tuple(self._bindings.values())):
            if binding.instance is not None:
                if binding.started and not binding.stopped:
                    raise RuntimeError("来源任务尚未停止，不能释放资源")
                await binding.instance.aclose()
                binding.instance = None
                self._publish(binding, "closed")
