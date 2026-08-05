"""按照平台选择规则组合一个运行时实例。

组合根通过统一的 ``PlatformHandle`` 协议管理所有平台的生命周期：
创建、工具绑定、任务启动和优雅停止均无需感知具体平台类型。
"""

from __future__ import annotations

import asyncio
import importlib
import signal
import webbrowser
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import uvicorn

from src.agents.triage import StructuredTriagePolicy
from src.ai.gateway import ModelGatewayService
from src.config import get as get_config
from src.contracts.agent import AgentHandler, Capability, EngineConfiguration
from src.contracts.configuration import PLATFORM_NAMES, PlatformPreference
from src.engine.runtime import AgentEngine
from src.localhost.api import create_debug_app
from src.localhost.runtime import AuroraRuntime
from src.memory.service import MemoryService
from src.prompt import PromptComposer, load_prompt_catalog
from src.utils.logging import configure_console_logging, configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.contracts.configuration import AuroraConfig, DashboardConfig
    from src.platform import PlatformHandle

logger = get_logger("aurora.process")

# -- 平台注册 ---------------------------------------------------------
# 每个平台子包通过同名模块函数 _create(config, runtime) -> PlatformHandle 接入组合根。
# 新增平台只需在本注册表中添加一条映射，无需修改任何组合逻辑。
_PLATFORM_CREATORS: dict[str, Callable[..., Any]] = {}


def _init_platforms() -> dict[str, Callable[..., Any]]:
    """一次性导入所有平台子包并将 _create 注册到本地映射。"""
    if _PLATFORM_CREATORS:
        return _PLATFORM_CREATORS
    for name in ("console", "dashboard", "mcp"):
        module = importlib.import_module(f"src.platform.{name}")
        if hasattr(module, "_create"):
            _PLATFORM_CREATORS[name] = module._create  # type: ignore[attr-defined]
    return _PLATFORM_CREATORS


# -- 内部辅助类型 -----------------------------------------------------


class _AuroraServer(uvicorn.Server):
    """禁止 uvicorn 自行捕获信号，由组合根统一管理停止流程。"""

    @__import__("contextlib").contextmanager
    def capture_signals(self):  # type: ignore[no-untyped-def]
        yield


class _DashboardStartupError(RuntimeError):
    """Dashboard 服务器在接收连接前就已停止。"""

    def __init__(self) -> None:
        super().__init__("Dashboard server stopped before accepting connections")


_SERVER_GRACE_SECONDS = 10.0
"""uvicorn 服务器优雅退出的等待上限，超时后强制取消。"""


@dataclass(frozen=True, slots=True)
class _InstalledSignal:
    """已注册的信号处理器快照，用于启动与恢复。"""

    candidate: signal.Signals
    loop_owned: bool
    previous: object | None = None


@dataclass(frozen=True, slots=True)
class _ProcessServers:
    """进程内由组合根管理的 HTTP 服务集合。"""

    dashboard: object | None
    debug: uvicorn.Server


# -- 主入口 -----------------------------------------------------------


async def run_runtime(
    platforms: frozenset[str] | None,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """围绕一个共享运行时和停止事件，启动精确的平台组合并运行至停止。"""
    configuration = get_config()
    selected = _selected_platforms(platforms, configuration.preference)
    configure_logging(configuration.logging_level, configuration.logging_dir / "aurora.log")
    configure_console_logging(enabled=configuration.preference.console.terminal_logs if "console" in selected else True)

    runtime = _create_runtime(configuration)
    stop = stop_event or asyncio.Event()
    runtime.bind_stop_requester(stop.set)
    debug_server = _debug_server(runtime)
    failure: BaseException | None = None
    async with AsyncExitStack() as resources:
        resources.push_async_callback(runtime.shutdown)
        installed_signals = _install_stop_handlers(stop) if stop_event is None else ()
        try:
            started = await _start_platforms_until_stop(runtime, selected, resources, stop)
            if started is not None:
                handles, dashboard_server = started
                logger.info(
                    "process started platforms=%s profile=%s",
                    ",".join(sorted(selected)) or "headless",
                    runtime.configuration.runtime.profile,
                )
                failure = await _run_platform_tasks(
                    runtime,
                    stop,
                    handles,
                    _ProcessServers(dashboard_server, debug_server),
                    open_browser=configuration.preference.dashboard.open_browser,
                )
        finally:
            runtime.bind_stop_requester(None)
            _restore_stop_handlers(installed_signals)
    logger.info("process stopped platforms=%s", ",".join(sorted(selected)) or "headless")
    if failure is not None:
        raise failure


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
    catalog = load_prompt_catalog(configuration.root, frozenset(profile.id for profile in profiles))
    composer = PromptComposer(catalog)
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
) -> tuple[dict[str, PlatformHandle], object | None]:
    """遍历已注册的平台描述符，为选中的平台创建实例、收集工具绑定与清理回调。

    返回 (handles, dashboard_server) —
    handles 为平台名到句柄的映射，dashboard_server 为非 None 时表示 HTTP 服务已就绪。
    """
    creators = _init_platforms()
    handles: dict[str, PlatformHandle] = {}
    all_bindings: list[Any] = []
    dashboard_server: object | None = None

    for name in sorted(selected):
        creator = creators.get(name)
        if creator is None:
            raise ValueError(f"no platform creator registered for {name}")
        handle: PlatformHandle = await creator(runtime.configuration, runtime)
        handles[name] = handle
        all_bindings.extend(handle.bindings)
        if handle.cleanup is not None:
            if asyncio.iscoroutinefunction(handle.cleanup):
                resources.push_async_callback(handle.cleanup)
            else:
                resources.callback(handle.cleanup)
        if name == "dashboard" and handle.http_server is not None:
            dashboard_server = handle.http_server

    if all_bindings:
        runtime.engine.bind_tool_executors(tuple(all_bindings))
    return handles, dashboard_server


async def _start_platforms_until_stop(
    runtime: AuroraRuntime,
    selected: frozenset[str],
    resources: AsyncExitStack,
    stop: asyncio.Event,
) -> tuple[dict[str, PlatformHandle], object | None] | None:
    """竞速启动平台与停止信号。"""
    startup = asyncio.create_task(_start_platforms(runtime, selected, resources), name="aurora-platform-startup")
    stop_task = asyncio.create_task(stop.wait(), name="aurora-startup-stop")
    done, _pending = await asyncio.wait({startup, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    if startup in done:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        return startup.result()
    startup.cancel()
    await asyncio.gather(startup, return_exceptions=True)
    return None


# -- 任务执行与停止 ----------------------------------------------------


async def _run_platform_tasks(
    runtime: AuroraRuntime,
    stop: asyncio.Event,
    handles: dict[str, PlatformHandle],
    servers: _ProcessServers,
    *,
    open_browser: bool,
) -> BaseException | None:
    """启动运行时循环和各平台后台任务，等待首个完成者并协调退出。"""
    runtime_task = asyncio.create_task(runtime.run_forever(stop), name="aurora-runtime-loop")
    tasks: set[asyncio.Task[None]] = {runtime_task}

    # 各平台通过 spawn 生成后台任务
    platform_tasks: dict[str, asyncio.Task[None]] = {}
    dashboard_task: asyncio.Task[None] | None = None
    for name, handle in handles.items():
        if handle.spawn is not None:
            task = handle.spawn(runtime, stop)
            if task is not None:
                platform_tasks[name] = task
                tasks.add(task)
                if name == "dashboard":
                    dashboard_task = task

    debug_task = asyncio.create_task(servers.debug.serve(), name="aurora-localhost-debug-server")
    tasks.add(debug_task)
    stop_task = asyncio.create_task(_wait_for_stop(stop), name="aurora-stop-watcher")
    tasks.add(stop_task)

    try:
        if dashboard_task is not None and open_browser and _await_server_ready(servers.dashboard, dashboard_task, stop):
            await asyncio.to_thread(_open_dashboard_browser, runtime.configuration.dashboard)

        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return _task_failure(done, stop_task, stop)
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        for name, task in platform_tasks.items():
            if name == "dashboard":
                continue
            task.cancel()
        await asyncio.gather(
            *(task for name, task in platform_tasks.items() if name != "dashboard"),
            return_exceptions=True,
        )
        if dashboard_task is not None and servers.dashboard is not None:
            # uvicorn 服务器必须通过 should_exit 优雅退出：直接取消会中断
            # lifespan 握手并在进程收尾时打印 CancelledError traceback。
            servers.dashboard.should_exit = True  # type: ignore[union-attr]
            await _await_server_exit(dashboard_task)
        servers.debug.should_exit = True
        await asyncio.gather(debug_task, return_exceptions=True)
        stop.set()
        await asyncio.gather(runtime_task, return_exceptions=True)


async def _wait_for_stop(stop: asyncio.Event) -> None:
    """挂起直到 stop 事件被设置。"""
    await stop.wait()


async def _await_server_exit(task: asyncio.Task[None]) -> None:
    """等待 uvicorn 服务器任务优雅退出，超时后强制取消。"""
    with suppress(TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(task), timeout=_SERVER_GRACE_SECONDS)
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _await_server_ready(server: object, task: asyncio.Task[None] | None, stop: asyncio.Event) -> bool:
    """轮询等待 HTTP 服务器完成启动，失败或提前停止时返回 False。"""
    assert task is not None
    while not getattr(server, "started", False):
        if stop.is_set():
            return False
        if task.done():
            task.result()
            raise _DashboardStartupError
        await asyncio.sleep(0.01)
    return True


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


# -- Dashboard 辅助 ----------------------------------------------------


def _open_dashboard_browser(configuration: DashboardConfig) -> None:
    """在默认浏览器中打开 Dashboard 地址。"""
    host = "127.0.0.1" if configuration.host in {"0.0.0.0", "::"} else configuration.host
    if ":" in host:
        host = f"[{host}]"
    webbrowser.open(f"http://{host}:{configuration.port}")


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
    return _AuroraServer(
        uvicorn.Config(
            create_debug_app(runtime),
            host=configuration.runtime.debug_host,
            port=configuration.runtime.debug_port,
            log_level=configuration.logging_level.lower(),
            log_config=None,
            access_log=False,
        )
    )
