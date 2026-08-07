"""按照平台选择规则组合一个运行时实例。

组合根通过统一的 ``PlatformHandle`` 协议管理所有平台的生命周期：
创建、工具绑定、任务启动和优雅停止均无需感知具体平台类型。
"""

from __future__ import annotations

import asyncio
import importlib
import signal
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import uvicorn

from src.agents.triage import StructuredTriagePolicy
from src.ai import ModelGatewayService
from src.config import get
from src.contracts import (
    PLATFORM_NAMES,
    AgentHandler,
    Capability,
    EngineConfiguration,
    PlatformPreference,
)
from src.engine.runtime import AgentEngine
from src.localhost.api import create_debug_app
from src.localhost.runtime import AuroraRuntime
from src.memory.service import MemoryService
from src.prompt import PromptCatalog, PromptComposer
from src.utils import (
    SignalSafeServer,
    configure_console_logging,
    configure_logging,
    get_logger,
)

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig
    from src.contracts.platform import PlatformCleanup, PlatformFactory, PlatformHandle, PlatformServer
    from src.contracts.tool import ToolExecutorBinding

logger = get_logger("aurora.process")


# -- 平台注册 ---------------------------------------------------------
def _init_platforms() -> dict[str, PlatformFactory]:
    """显式注册平台工厂，使签名漂移在静态检查阶段失败。"""
    from src.platform.dashboard import _create as create_dashboard
    from src.platform.mcp import _create as create_mcp

    creators: dict[str, PlatformFactory] = {"dashboard": create_dashboard, "mcp": create_mcp}
    if creators.keys() != PLATFORM_NAMES:
        raise RuntimeError("platform factory registry does not match PlatformPreference")
    return creators


# -- 内部辅助类型 -----------------------------------------------------


_SERVER_GRACE_SECONDS = 10.0
"""平台 server 优雅退出的等待上限，超时后强制取消。"""
_CANCEL_GRACE_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class _InstalledSignal:
    """已注册的信号处理器快照，用于启动与恢复。"""

    candidate: signal.Signals
    loop_owned: bool
    previous: object | None = None


# -- 主入口 -----------------------------------------------------------


async def run_runtime(
    platforms: frozenset[str] | None,
    *,
    headless: bool = False,
    stop_event: asyncio.Event | None = None,
) -> None:
    """围绕一个共享运行时和停止事件，启动精确的平台组合并运行至停止。

    headless 只禁用本地 Console，不改变平台组合。
    """
    configuration = get()
    selected = _selected_platforms(platforms, configuration.preference)
    console_enabled = not headless and configuration.runtime.console.enabled
    configure_logging(configuration.logging_level, configuration.logging_dir / "aurora.log")
    configure_console_logging(enabled=configuration.runtime.console.terminal_logs)

    runtime = _create_runtime(configuration)
    stop = stop_event or asyncio.Event()
    runtime.bind_stop_requester(stop.set)
    debug_server = _debug_server(runtime)
    failure: BaseException | None = None
    async with AsyncExitStack() as resources:
        resources.push_async_callback(_run_cleanup, runtime.shutdown)
        installed_signals = _install_stop_handlers(stop) if stop_event is None else ()
        try:
            handles = await _start_platforms_until_stop(runtime, selected, resources, stop)
            if handles is not None:
                logger.info(
                    "process started platforms=%s profile=%s",
                    _platforms_label(selected),
                    runtime.configuration.runtime.profile,
                )
                failure = await _run_platform_tasks(
                    runtime,
                    stop,
                    handles,
                    debug_server,
                    console_enabled=console_enabled,
                )
        finally:
            runtime.bind_stop_requester(None)
            _restore_stop_handlers(installed_signals)
    logger.info("process stopped platforms=%s", _platforms_label(selected))
    if failure is not None:
        raise failure


def _platforms_label(selected: frozenset[str]) -> str:
    """平台集合的日志标签，空集合表示为 headless。"""
    return ",".join(sorted(selected)) or "headless"


# -- 平台选择 ---------------------------------------------------------


def _selected_platforms(platforms: frozenset[str] | None, preference: PlatformPreference) -> frozenset[str]:
    """由用户指定的平台或配置偏好推导出本次应启用的平台集合。"""
    if platforms is not None:
        unknown = platforms - PLATFORM_NAMES
        if unknown:
            raise ValueError(f"unknown platforms: {sorted(unknown)}")
        return platforms
    return frozenset(name for name in PLATFORM_NAMES if getattr(preference, name).enabled)


# -- Agent handler 加载 -------------------------------------------------


def _load_handler(specification: str, composer: PromptComposer, capabilities: tuple[Capability, ...]) -> AgentHandler:
    """加载 Agent handler，并注入提示词装配器与主动能力。"""
    module_name, separator, attribute = specification.partition(":")
    if not separator:
        raise ValueError(f"Agent implementation must use module:attribute syntax: {specification}")
    implementation = getattr(importlib.import_module(module_name), attribute)
    handler: Any = implementation()
    installer = getattr(handler, "install_prompt_composer", None)
    if callable(installer):
        installer(composer)
    cap_installer = getattr(handler, "install_capabilities", None)
    if callable(cap_installer):
        cap_installer(capabilities)
    if not callable(getattr(handler, "handle", None)):
        raise TypeError(f"Agent implementation does not provide handle(): {specification}")
    return handler


def _build_capabilities() -> tuple[Capability, ...]:
    """构造 Agent 可主动选择的内建能力。"""
    from src.agents.capabilities.delegate import DelegationCapability
    from src.agents.capabilities.speech import SpeechCapability
    from src.agents.capabilities.wait import WaitCapability

    return DelegationCapability(), WaitCapability(), SpeechCapability()


# -- Engine / localhost 构造 --------------------------------------------


def _create_runtime(configuration: AuroraConfig) -> AuroraRuntime:
    """在唯一组合根创建 Agent、Provider、自动服务、engine 与 localhost。"""
    profiles = configuration.agents
    limits = configuration.engine.agents
    engine_configuration = EngineConfiguration(
        workspace=str(configuration.engine.workspace),
        profiles=profiles,
        limits=limits,
        interactive_budget=configuration.engine.interactive_budget,
        autonomous_budget=configuration.engine.autonomous_budget,
        triage=configuration.engine.triage,
    )
    memory = MemoryService(configuration.storage.memory)
    composer = PromptComposer(PromptCatalog.from_config(configuration.prompts))
    capabilities = _build_capabilities()
    handlers = {profile.id: _load_handler(profile.implementation, composer, capabilities) for profile in profiles}
    engine = AgentEngine(
        engine_configuration,
        handlers,
        model_provider=ModelGatewayService(configuration),
        triage_policy=StructuredTriagePolicy(configuration.engine.triage),
        memory_store=memory,
        idle_wait_seconds=configuration.engine.autonomy.scan_seconds,
    )
    return AuroraRuntime(configuration, engine)


# -- 平台启动（统一循环）-----------------------------------------------


async def _start_platforms(
    runtime: AuroraRuntime,
    selected: frozenset[str],
    resources: AsyncExitStack,
) -> dict[str, PlatformHandle]:
    """遍历已注册的平台描述符，为选中的平台创建实例并收集工具绑定与清理回调。

    平台的 server 与后台任务不在此启动，统一由 ``_run_platform_tasks`` 调度。
    """
    creators = _init_platforms()
    handles: dict[str, PlatformHandle] = {}
    all_bindings: list[ToolExecutorBinding] = []

    for name in sorted(selected):
        creator = creators.get(name)
        if creator is None:
            raise ValueError(f"no platform creator registered for {name}")
        handle = await creator(runtime.configuration, runtime)
        handles[name] = handle
        all_bindings.extend(handle.bindings)
        if handle.cleanup is not None:
            resources.push_async_callback(_run_cleanup, handle.cleanup)

    runtime.engine.bind_tool_executors(tuple(all_bindings))
    return handles


async def _start_platforms_until_stop(
    runtime: AuroraRuntime,
    selected: frozenset[str],
    resources: AsyncExitStack,
    stop: asyncio.Event,
) -> dict[str, PlatformHandle] | None:
    """竞速启动平台与停止信号。"""
    startup = asyncio.create_task(_start_platforms(runtime, selected, resources), name="aurora-platform-startup")
    stop_task = asyncio.create_task(stop.wait(), name="aurora-startup-stop")
    try:
        done, _pending = await asyncio.wait({startup, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        return startup.result() if startup in done else None
    finally:
        await asyncio.gather(*(_cancel_task(task) for task in (startup, stop_task)))


# -- 任务执行与停止 ----------------------------------------------------


async def _run_platform_tasks(
    runtime: AuroraRuntime,
    stop: asyncio.Event,
    handles: dict[str, PlatformHandle],
    debug_server: PlatformServer,
    *,
    console_enabled: bool,
) -> BaseException | None:
    """启动运行时循环和各平台后台任务，等待首个完成者并协调退出。"""
    runtime_task = asyncio.create_task(runtime.run_forever(stop), name="aurora-runtime-loop")
    tasks: set[asyncio.Task[None]] = {runtime_task}

    # 平台 server 通过 should_exit 优雅退出；background 必须持续运行到 stop。
    servers: dict[str, PlatformServer] = {}
    server_tasks: dict[str, asyncio.Task[None]] = {}
    platform_tasks: dict[str, asyncio.Task[None]] = {}
    for name, handle in handles.items():
        if handle.server is not None:
            servers[name] = handle.server
            task = asyncio.create_task(handle.server.serve(), name=f"aurora-platform-{name}-server")
            server_tasks[name] = task
            tasks.add(task)
        if handle.background is not None:
            task = asyncio.create_task(handle.background(stop), name=f"aurora-platform-{name}-background")
            platform_tasks[name] = task
            tasks.add(task)

    console_task: asyncio.Task[None] | None = _spawn_console(runtime, stop, enabled=console_enabled)
    tasks.update(task for task in (console_task,) if task is not None)

    debug_task = asyncio.create_task(debug_server.serve(), name="aurora-localhost-debug-server")
    tasks.add(debug_task)
    stop_task = asyncio.create_task(_wait_for_stop(stop), name="aurora-stop-watcher")
    tasks.add(stop_task)

    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return _task_failure(done, stop_task, stop)
    finally:
        stop.set()
        await _cancel_task(stop_task)
        await asyncio.gather(
            *(_stop_server(servers[name], task) for name, task in server_tasks.items()),
            *(_await_task_exit(task) for task in platform_tasks.values()),
            *(_await_task_exit(task) for task in (console_task,) if task is not None),
            _stop_server(debug_server, debug_task),
            _await_task_exit(runtime_task),
        )


async def _wait_for_stop(stop: asyncio.Event) -> None:
    """挂起直到 stop 事件被设置。"""
    await stop.wait()


def _spawn_console(runtime: AuroraRuntime, stop: asyncio.Event, *, enabled: bool) -> asyncio.Task[None] | None:
    """按运行时配置创建本地 Console 前端任务（headless 或配置禁用时不启动）。"""
    if not enabled:
        return None
    from src.console import run_console

    return asyncio.create_task(run_console(runtime, runtime, stop_event=stop), name="aurora-console")


async def _stop_server(server: PlatformServer, task: asyncio.Task[None]) -> None:
    """请求 server 退出且不让其原异常中断其他资源清理。"""
    server.should_exit = True
    await _await_task_exit(task)


async def _await_task_exit(task: asyncio.Task[None]) -> None:
    """有界等待任务退出，超时后取消并吸收原任务异常。"""
    if not task.done():
        await asyncio.wait({task}, timeout=_SERVER_GRACE_SECONDS)
    if not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=_CANCEL_GRACE_SECONDS)
    if task.done():
        await asyncio.gather(task, return_exceptions=True)
    else:
        logger.error("task ignored cancellation task=%s", task.get_name())


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    """取消任务并有界回收。"""
    if not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=_CANCEL_GRACE_SECONDS)
    if task.done():
        await asyncio.gather(task, return_exceptions=True)
    else:
        logger.error("task ignored cancellation task=%s", task.get_name())


async def _run_cleanup(cleanup: PlatformCleanup) -> None:
    """在统一期限内执行资源清理回调。"""
    task = asyncio.create_task(cleanup(), name="aurora-resource-cleanup")
    await _await_task_exit(task)
    if not task.done() or task.cancelled():
        raise TimeoutError("resource cleanup did not finish")
    if error := task.exception():
        raise error


def _task_failure(
    done: set[asyncio.Task[None]], stop_task: asyncio.Task[None], stop: asyncio.Event
) -> BaseException | None:
    """从已完成的任务中提取异常或检测意外退出。"""
    for task in done:
        if task is stop_task or task.cancelled():
            continue
        try:
            task.result()
        except BaseException as error:  # noqa: BLE001
            return error
        if not stop.is_set():
            return RuntimeError(f"{task.get_name()} stopped unexpectedly")
    return None


# -- 信号处理 ----------------------------------------------------------


def _install_stop_handlers(stop: asyncio.Event) -> tuple[_InstalledSignal, ...]:
    """在事件循环上安装 SIGINT/SIGTERM 信号处理器。"""
    loop = asyncio.get_running_loop()
    installed: list[_InstalledSignal] = []
    for candidate in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(candidate, stop.set)
        except (NotImplementedError, RuntimeError):
            previous = signal.getsignal(candidate)

            def handle_signal(_signum: int, _frame: object, *, event: asyncio.Event = stop) -> None:
                loop.call_soon_threadsafe(event.set)

            signal.signal(candidate, handle_signal)
            installed.append(_InstalledSignal(candidate=candidate, loop_owned=False, previous=previous))
        else:
            installed.append(_InstalledSignal(candidate=candidate, loop_owned=True))
    return tuple(installed)


def _restore_stop_handlers(installed: tuple[_InstalledSignal, ...]) -> None:
    """恢复之前安装的信号处理器。"""
    loop = asyncio.get_running_loop()
    for item in installed:
        if item.loop_owned:
            loop.remove_signal_handler(item.candidate)
        else:
            signal.signal(item.candidate, item.previous)  # type: ignore[arg-type]


# -- 调试服务器 --------------------------------------------------------


def _debug_server(runtime: AuroraRuntime) -> uvicorn.Server:
    """创建独立于 Platform 集合的 localhost 调试服务器。"""
    configuration = runtime.configuration
    return SignalSafeServer(
        uvicorn.Config(
            create_debug_app(runtime),
            host=configuration.runtime.debug_host,
            port=configuration.runtime.debug_port,
            log_level=configuration.logging_level.lower(),
            log_config=None,
            access_log=False,
        )
    )
