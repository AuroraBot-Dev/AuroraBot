"""按照 RFC 0014 的平台选择规则组合一个运行时实例。"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import signal
import webbrowser
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import uvicorn

from src.ai.vnext import ModelGatewayService
from src.config import get as get_config
from src.contracts.agent import AgentHandler, Capability, EngineConfiguration
from src.contracts.configuration import PLATFORM_NAMES, PlatformPreference
from src.contracts.tool import ToolExecutorBinding
from src.engine.runtime import AgentEngine
from src.localhost.api import create_debug_app
from src.localhost.runtime import AuroraRuntime
from src.memory.service import MemoryService
from src.platform.console import CONSOLE_SEND_DESCRIPTOR, ConsolePlatform
from src.platform.console.shell import run_console
from src.platform.dashboard import DASHBOARD_SEND_DESCRIPTOR, ChatService, DashboardPlatform, create_app
from src.platform.mcp import MCPPlatform
from src.prompt import PromptComposer, load_prompt_catalog
from src.utils.logging import configure_console_logging, configure_logging, get_logger

logger = get_logger("aurora.process")

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig, DashboardConfig


class _AuroraServer(uvicorn.Server):
    """将进程信号的所有权留给 Aurora 组合根，禁止 uvicorn 自行捕获信号。"""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[no-untyped-def]
        yield


class _DashboardStartupError(RuntimeError):
    """Dashboard 服务器在接收连接前就已停止。"""

    def __init__(self) -> None:
        super().__init__("Dashboard server stopped before accepting connections")


@dataclass(frozen=True, slots=True)
class _InstalledSignal:
    """已注册的信号处理器快照，用于启动与恢复。"""

    candidate: signal.Signals
    loop_owned: bool
    previous: object | None = None


@dataclass(frozen=True, slots=True)
class _ProcessServers:
    """进程内由组合根管理的 HTTP 服务。"""

    dashboard: uvicorn.Server | None
    debug: uvicorn.Server


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
    debug_server = _debug_server(runtime)
    stop = stop_event or asyncio.Event()
    runtime.bind_stop_requester(stop.set)
    failure: BaseException | None = None
    async with AsyncExitStack() as resources:
        resources.push_async_callback(runtime.shutdown)
        # 仅当外部未提供 stop_event 时安装信号处理器，避免重复安装
        installed_signals = _install_stop_handlers(stop) if stop_event is None else ()
        try:
            started = await _start_platforms_until_stop(runtime, configuration.preference, selected, resources, stop)
            if started is not None:
                console_platform, server = started
                logger.info(
                    "process started platforms=%s profile=%s",
                    ",".join(sorted(selected)) or "headless",
                    runtime.configuration.runtime.profile,
                )
                failure = await _run_platform_tasks(
                    runtime,
                    stop,
                    console_platform,
                    _ProcessServers(server, debug_server),
                    open_browser=configuration.preference.dashboard.open_browser,
                )
        finally:
            runtime.bind_stop_requester(None)
            _restore_stop_handlers(installed_signals)
    logger.info("process stopped platforms=%s", ",".join(sorted(selected)) or "headless")
    if failure is not None:
        raise failure


def _selected_platforms(platforms: frozenset[str] | None, preference: PlatformPreference) -> frozenset[str]:
    """由用户指定的平台或配置偏好推导出本次应启用的平台集合。"""
    if platforms is not None:
        unknown = platforms - PLATFORM_NAMES
        if unknown:
            message = f"unknown platforms: {sorted(unknown)}"
            raise ValueError(message)
        return platforms
    return frozenset(name for name in PLATFORM_NAMES if getattr(preference, name).enabled)


def _load_handler(
    specification: str,
    composer: PromptComposer,
    capabilities: tuple[Capability, ...],
) -> AgentHandler:
    """加载 Agent handler，并注入提示词装配器与主动能力。"""
    module_name, separator, attribute = specification.partition(":")
    if not separator:
        raise ValueError(f"Agent implementation must use module:attribute syntax: {specification}")
    implementation = getattr(importlib.import_module(module_name), attribute)
    handler: Any = implementation()
    composer_installer = getattr(handler, "install_prompt_composer", None)
    if callable(composer_installer):
        composer_installer(composer)
    capability_installer = getattr(handler, "install_capabilities", None)
    if callable(capability_installer):
        capability_installer(capabilities)
    if not callable(getattr(handler, "handle", None)):
        raise TypeError(f"Agent implementation does not provide handle(): {specification}")
    return handler


def _build_capabilities() -> tuple[Capability, ...]:
    """构造 Agent 可主动选择的内建能力。"""
    from src.agents.capabilities.claim import ClaimCapability
    from src.agents.capabilities.delegate import DelegationCapability
    from src.agents.capabilities.wait import WaitCapability

    return DelegationCapability(), WaitCapability(), ClaimCapability()


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
    )
    memory = MemoryService(configuration, configuration.storage.memory)
    catalog = load_prompt_catalog(configuration.root, frozenset(profile.id for profile in profiles))
    composer = PromptComposer(catalog)
    capabilities = _build_capabilities()
    handlers = {profile.id: _load_handler(profile.implementation, composer, capabilities) for profile in profiles}
    engine = AgentEngine(
        engine_configuration,
        handlers,
        model_provider=ModelGatewayService(configuration),
        memory_store=memory,
        idle_wait_seconds=configuration.engine.autonomy.scan_seconds,
    )
    return AuroraRuntime(configuration, engine)


async def _start_platforms(
    runtime: AuroraRuntime,
    preference: PlatformPreference,
    selected: frozenset[str],
    resources: AsyncExitStack,
) -> tuple[ConsolePlatform | None, uvicorn.Server | None]:
    """按选中集合创建并启动各平台实例，绑定工具执行器。"""
    console_platform = (
        ConsolePlatform(runtime.configuration.storage.console / "runtime.sqlite3") if "console" in selected else None
    )
    if console_platform is not None:
        resources.callback(console_platform.close)
    dashboard_platform: DashboardPlatform | None = None
    server: uvicorn.Server | None = None
    if "dashboard" in selected:
        dashboard_platform, server = await _create_dashboard(runtime)
    mcp_platform: MCPPlatform | None = None
    if "mcp" in selected:
        mcp_platform = MCPPlatform(
            runtime.configuration,
            terminal_logs=preference.mcp.terminal_logs,
        )
        resources.push_async_callback(mcp_platform.shutdown)
        await mcp_platform.start(runtime)
    _bind_platform_tools(runtime, console_platform, dashboard_platform, mcp_platform)
    return console_platform, server


async def _start_platforms_until_stop(
    runtime: AuroraRuntime,
    preference: PlatformPreference,
    selected: frozenset[str],
    resources: AsyncExitStack,
    stop: asyncio.Event,
) -> tuple[ConsolePlatform | None, uvicorn.Server | None] | None:
    """竞速启动平台与停止信号：平台先就绪返回结果，先收到停止信号则返回 None。"""
    startup_task = asyncio.create_task(
        _start_platforms(runtime, preference, selected, resources),
        name="aurora-platform-startup",
    )
    stop_task = asyncio.create_task(stop.wait(), name="aurora-startup-stop")
    done, _pending = await asyncio.wait({startup_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    if startup_task in done:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        return startup_task.result()
    startup_task.cancel()
    await asyncio.gather(startup_task, return_exceptions=True)
    return None


async def _run_platform_tasks(
    runtime: AuroraRuntime,
    stop: asyncio.Event,
    console_platform: ConsolePlatform | None,
    servers: _ProcessServers,
    *,
    open_browser: bool,
) -> BaseException | None:
    """启动运行时循环、Dashboard 服务、Console 和停止监控等协程任务，等待首个完成者。

    返回首个非正常退出任务捕获的异常，正常停止时返回 None。
    """
    runtime_task = asyncio.create_task(runtime.run_forever(stop), name="aurora-runtime-loop")
    tasks: set[asyncio.Task[None]] = {runtime_task}
    server_task: asyncio.Task[None] | None = None
    if servers.dashboard is not None:
        server_task = asyncio.create_task(servers.dashboard.serve(), name="aurora-dashboard-server")
        tasks.add(server_task)
    debug_task = asyncio.create_task(servers.debug.serve(), name="aurora-localhost-debug-server")
    tasks.add(debug_task)
    console_task: asyncio.Task[None] | None = None
    if console_platform is not None:
        console_task = asyncio.create_task(
            run_console(runtime, console_platform, stop_event=stop),
            name="aurora-console",
        )
        tasks.add(console_task)
    stop_task = asyncio.create_task(_wait_for_stop(stop), name="aurora-stop-watcher")
    tasks.add(stop_task)
    try:
        # 服务器就绪后自动打开浏览器
        if (
            servers.dashboard is not None
            and open_browser
            and await _wait_for_server_start(servers.dashboard, server_task, stop)
        ):
            await asyncio.to_thread(_open_dashboard_browser, runtime.configuration.dashboard)
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return _task_failure(done, stop_task, stop)
    finally:
        # 按顺序退出：停止监控 → Console → Dashboard → 运行时
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        if console_task is not None:
            console_task.cancel()
            await asyncio.gather(console_task, return_exceptions=True)
        if servers.dashboard is not None and server_task is not None:
            servers.dashboard.should_exit = True
            await asyncio.gather(server_task, return_exceptions=True)
        servers.debug.should_exit = True
        await asyncio.gather(debug_task, return_exceptions=True)
        stop.set()
        await asyncio.gather(runtime_task, return_exceptions=True)


async def _wait_for_stop(stop: asyncio.Event) -> None:
    """挂起直到 stop 事件被设置。"""
    await stop.wait()


async def _wait_for_server_start(
    server: uvicorn.Server,
    server_task: asyncio.Task[None] | None,
    stop: asyncio.Event,
) -> bool:
    """轮询等待 uvicorn 服务器完成启动，失败或提前停止时返回 False。"""
    assert server_task is not None
    while not server.started:
        if stop.is_set():
            return False
        if server_task.done():
            server_task.result()
            raise _DashboardStartupError
        await asyncio.sleep(0.01)
    return True


def _task_failure(
    done: set[asyncio.Task[None]],
    stop_task: asyncio.Task[None],
    stop: asyncio.Event,
) -> BaseException | None:
    """从已完成的任务中提取异常或检测意外退出。

    跳过停止监控任务和已取消任务；若某个任务在未设置停止事件的情况下退出，视为意外。
    """
    for task in done:
        if task is stop_task or task.cancelled():
            continue
        try:
            task.result()
        except BaseException as error:  # noqa: BLE001 - re-raised after coordinated cleanup.
            return error
        if not stop.is_set():
            return RuntimeError(f"{task.get_name()} stopped unexpectedly")
    return None


async def _create_dashboard(runtime: AuroraRuntime) -> tuple[DashboardPlatform, uvicorn.Server]:
    """创建 ChatService 与 DashboardPlatform，并构建对应的 uvicorn 服务器。"""
    chat = ChatService(runtime.configuration.dashboard, runtime)
    await chat.start()
    return DashboardPlatform(chat), _dashboard_server(chat, runtime)


def _dashboard_server(chat: ChatService, runtime: AuroraRuntime) -> uvicorn.Server:
    """用自定义的 _AuroraServer 包装 uvicorn，禁止其接管进程信号。"""
    dashboard = runtime.configuration.dashboard
    return _AuroraServer(
        uvicorn.Config(
            create_app(
                chat,
                runtime,
                dashboard,
                profile=runtime.configuration.runtime.profile,
            ),
            host=dashboard.host,
            port=dashboard.port,
            log_level=runtime.configuration.logging_level.lower(),
            log_config=None,
            access_log=False,
        )
    )


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


def _open_dashboard_browser(configuration: DashboardConfig) -> None:
    """在默认浏览器中打开 Dashboard 地址，支持 IPv6 的 ``[::1]`` 格式。"""
    host = "127.0.0.1" if configuration.host in {"0.0.0.0", "::"} else configuration.host
    if ":" in host:
        host = f"[{host}]"
    webbrowser.open(f"http://{host}:{configuration.port}")


def _bind_platform_tools(
    runtime: AuroraRuntime,
    console_platform: ConsolePlatform | None,
    dashboard_platform: DashboardPlatform | None,
    mcp_platform: MCPPlatform | None,
) -> None:
    """将已启用平台的工具执行器统一绑定到运行时。"""
    tool_bindings = []
    if console_platform is not None:
        tool_bindings.append(
            ToolExecutorBinding(
                CONSOLE_SEND_DESCRIPTOR,
                console_platform,
                source_app="platform.console",
                source_instance="local",
                recovery=console_platform,
            )
        )
    if dashboard_platform is not None:
        tool_bindings.append(
            ToolExecutorBinding(
                DASHBOARD_SEND_DESCRIPTOR,
                dashboard_platform,
                source_app="platform.dashboard",
                source_instance="local",
                recovery=dashboard_platform,
            )
        )
    if mcp_platform is not None:
        tool_bindings.extend(
            ToolExecutorBinding(
                capability,
                mcp_platform,
                source_app="platform.mcp",
                source_instance=mcp_platform.source_instance_for(capability.id),
            )
            for capability in mcp_platform.capability_catalog.capabilities
        )
    runtime.engine.bind_tool_executors(tuple(tool_bindings))


def _install_stop_handlers(stop: asyncio.Event) -> tuple[_InstalledSignal, ...]:
    """在事件循环上安装 SIGINT/SIGTERM 信号处理器，用于安全停止。

    优先使用 asyncio 原生信号处理器；在不支持的平台（如某些 Windows 环境）上回退到
    signal.signal()，并通过 call_soon_threadsafe 连接 stop 事件。
    """
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
    """恢复通过 _install_stop_handlers 安装的信号处理器到之前的状态。"""
    loop = asyncio.get_running_loop()
    for item in installed:
        if item.loop_owned:
            loop.remove_signal_handler(item.candidate)
        else:
            signal.signal(item.candidate, item.previous)  # type: ignore[arg-type]
