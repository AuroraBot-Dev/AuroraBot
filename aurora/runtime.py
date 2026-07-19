"""Compose one Runtime with the exact RFC 0014 Platform selection."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import webbrowser
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

import uvicorn

from src.contracts.configuration import load_configuration
from src.contracts.configuration_preferences import PreferenceConfig, load_preference
from src.localhost.ports import EffectExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.console import CONSOLE_SEND_DESCRIPTOR, ConsolePlatform
from src.platform.console.shell import run_console
from src.platform.dashboard import DASHBOARD_REPLY_DESCRIPTOR, ChatService, DashboardPlatform, create_app
from src.platform.mcp import MCPPlatform
from src.utils.log_utils import configure_console_logging, configure_logging, get_logger

logger = get_logger("aurora.process")

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.configuration import DashboardConfig

PLATFORM_NAMES = frozenset({"console", "dashboard", "mcp"})


class _AuroraServer(uvicorn.Server):
    """Leave process signal ownership to the Aurora composition root."""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[no-untyped-def]
        yield


class _DashboardStartupError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Dashboard server stopped before accepting connections")


@dataclass(frozen=True, slots=True)
class _InstalledSignal:
    candidate: signal.Signals
    loop_owned: bool
    previous: object | None = None


async def run_runtime(
    root: Path,
    profile: str | None,
    platforms: frozenset[str] | None,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run one exact Platform composition around one shared Runtime and stop event."""
    resolved_root = await asyncio.to_thread(root.resolve)
    configuration = await asyncio.to_thread(load_configuration, resolved_root, profile)
    preference = await asyncio.to_thread(load_preference, resolved_root)
    selected = _selected_platforms(platforms, preference)
    configure_logging(configuration.logging_level, configuration.root / "logs" / "aurora.log")
    configure_console_logging(enabled=preference.platform.console.terminal_logs if "console" in selected else True)

    runtime = AuroraRuntime.create(
        resolved_root,
        profile,
        configuration=configuration,
        executor_bindings=None,
    )
    stop = stop_event or asyncio.Event()
    runtime.bind_stop_requester(stop.set)
    failure: BaseException | None = None
    async with AsyncExitStack() as resources:
        resources.push_async_callback(runtime.shutdown)
        installed_signals = _install_stop_handlers(stop) if stop_event is None else ()
        try:
            started = await _start_platforms_until_stop(runtime, preference, selected, resources, stop)
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
                    server,
                    open_browser=preference.platform.dashboard.open_browser,
                )
        finally:
            runtime.bind_stop_requester(None)
            _restore_stop_handlers(installed_signals)
    logger.info("process stopped platforms=%s", ",".join(sorted(selected)) or "headless")
    if failure is not None:
        raise failure


def _selected_platforms(platforms: frozenset[str] | None, preference: PreferenceConfig) -> frozenset[str]:
    if platforms is not None:
        unknown = platforms - PLATFORM_NAMES
        if unknown:
            message = f"unknown platforms: {sorted(unknown)}"
            raise ValueError(message)
        return platforms
    return frozenset(name for name in PLATFORM_NAMES if getattr(preference.platform, name).enabled)


async def _start_platforms(
    runtime: AuroraRuntime,
    preference: PreferenceConfig,
    selected: frozenset[str],
    resources: AsyncExitStack,
) -> tuple[ConsolePlatform | None, uvicorn.Server | None]:
    console_platform = ConsolePlatform() if "console" in selected else None
    dashboard_platform: DashboardPlatform | None = None
    server: uvicorn.Server | None = None
    if "dashboard" in selected:
        dashboard_platform, server = await _create_dashboard(runtime)
    mcp_platform: MCPPlatform | None = None
    if "mcp" in selected:
        mcp_platform = MCPPlatform(
            runtime.configuration,
            terminal_logs=preference.platform.mcp.terminal_logs,
        )
        resources.push_async_callback(mcp_platform.shutdown)
        await mcp_platform.start(runtime)
    _bind_effect_executors(runtime, console_platform, dashboard_platform, mcp_platform)
    return console_platform, server


async def _start_platforms_until_stop(
    runtime: AuroraRuntime,
    preference: PreferenceConfig,
    selected: frozenset[str],
    resources: AsyncExitStack,
    stop: asyncio.Event,
) -> tuple[ConsolePlatform | None, uvicorn.Server | None] | None:
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
    server: uvicorn.Server | None,
    *,
    open_browser: bool,
) -> BaseException | None:
    runtime_task = asyncio.create_task(runtime.run_forever(stop), name="aurora-runtime-loop")
    tasks: set[asyncio.Task[None]] = {runtime_task}
    server_task: asyncio.Task[None] | None = None
    if server is not None:
        server_task = asyncio.create_task(server.serve(), name="aurora-dashboard-server")
        tasks.add(server_task)
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
        if server is not None and open_browser and await _wait_for_server_start(server, server_task, stop):
            await asyncio.to_thread(_open_dashboard_browser, runtime.configuration.dashboard)
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return _task_failure(done, stop_task, stop)
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        if console_task is not None:
            console_task.cancel()
            await asyncio.gather(console_task, return_exceptions=True)
        if server is not None and server_task is not None:
            server.should_exit = True
            await asyncio.gather(server_task, return_exceptions=True)
        stop.set()
        await asyncio.gather(runtime_task, return_exceptions=True)


async def _wait_for_stop(stop: asyncio.Event) -> None:
    await stop.wait()


async def _wait_for_server_start(
    server: uvicorn.Server,
    server_task: asyncio.Task[None] | None,
    stop: asyncio.Event,
) -> bool:
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
    chat = ChatService(runtime.configuration.dashboard, runtime)
    await chat.start()
    return DashboardPlatform(chat.deliver_bot_reply), _dashboard_server(chat, runtime)


def _dashboard_server(chat: ChatService, runtime: AuroraRuntime) -> uvicorn.Server:
    dashboard = runtime.configuration.dashboard
    return _AuroraServer(
        uvicorn.Config(
            create_app(
                chat,
                runtime,
                runtime,
                dashboard,
                profile=runtime.configuration.runtime.profile,
            ),
            host=dashboard.host,
            port=dashboard.port,
            log_level=runtime.configuration.logging_level.lower(),
        )
    )


def _open_dashboard_browser(configuration: DashboardConfig) -> None:
    host = "127.0.0.1" if configuration.host in {"0.0.0.0", "::"} else configuration.host
    if ":" in host:
        host = f"[{host}]"
    webbrowser.open(f"http://{host}:{configuration.port}")


def _bind_effect_executors(
    runtime: AuroraRuntime,
    console_platform: ConsolePlatform | None,
    dashboard_platform: DashboardPlatform | None,
    mcp_platform: MCPPlatform | None,
) -> None:
    bindings = []
    if console_platform is not None:
        bindings.append(
            EffectExecutorBinding(
                CONSOLE_SEND_DESCRIPTOR,
                console_platform,
                source_app="platform.console",
                source_instance="local",
            )
        )
    if dashboard_platform is not None:
        bindings.append(
            EffectExecutorBinding(
                DASHBOARD_REPLY_DESCRIPTOR,
                dashboard_platform,
                source_app="platform.dashboard",
                source_instance="local",
            )
        )
    if mcp_platform is not None:
        bindings.extend(
            EffectExecutorBinding(
                capability,
                mcp_platform,
                source_app="platform.mcp",
                source_instance=capability.id.rpartition(".")[0],
            )
            for capability in mcp_platform.capability_catalog.capabilities
        )
    runtime.bind_effect_executors(tuple(bindings))


def _install_stop_handlers(stop: asyncio.Event) -> tuple[_InstalledSignal, ...]:
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
    loop = asyncio.get_running_loop()
    for item in installed:
        if item.loop_owned:
            loop.remove_signal_handler(item.candidate)
        else:
            signal.signal(item.candidate, item.previous)  # type: ignore[arg-type]
