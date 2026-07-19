"""Unified ownership of Runtime, Dashboard, Console, signals, and shutdown."""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass
from typing import TYPE_CHECKING

import uvicorn

from src.dashboard.api import create_app
from src.localhost.runtime import AuroraRuntime
from src.localhost.shell import run_console
from src.utils.log_utils import get_logger

logger = get_logger("aurora.process")

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeMode:
    name: str
    dashboard: bool
    console: bool


DEV = RuntimeMode("dev", dashboard=True, console=True)
RUN = RuntimeMode("run", dashboard=False, console=False)
SERVE = RuntimeMode("serve", dashboard=True, console=False)
CONSOLE = RuntimeMode("console", dashboard=False, console=True)


async def run_runtime(
    root: Path,
    profile: str | None,
    mode: RuntimeMode,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run one selected surface composition around exactly one Runtime."""
    resolved_root = await asyncio.to_thread(root.resolve)
    runtime = AuroraRuntime.create(resolved_root, profile, console_logging=not mode.console)
    stop = stop_event or asyncio.Event()
    runtime.bind_stop_requester(stop.set)
    installed_signals = _install_stop_handlers(stop) if stop_event is None else ()
    server: uvicorn.Server | None = None
    tasks: set[asyncio.Task[object]] = set()
    stop_task: asyncio.Task[object] | None = None
    failure: BaseException | None = None
    try:
        server = _dashboard_server(runtime) if mode.dashboard else None
        tasks.add(asyncio.create_task(runtime.run_forever(stop), name="aurora-runtime-loop"))
        if server is not None:
            tasks.add(asyncio.create_task(server.serve(), name="aurora-dashboard-server"))
        if mode.console:
            tasks.add(asyncio.create_task(run_console(runtime, stop_event=stop), name="aurora-console"))
        stop_task = asyncio.create_task(stop.wait(), name="aurora-stop-watcher")
        tasks.add(stop_task)
        logger.info("process started mode=%s profile=%s", mode.name, runtime.configuration.runtime.profile)
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is stop_task or task.cancelled():
                continue
            try:
                task.result()
            except BaseException as error:  # noqa: BLE001 - re-raised after coordinated cleanup.
                failure = error
                break
    finally:
        stop.set()
        if server is not None:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
        runtime.bind_stop_requester(None)
        loop = asyncio.get_running_loop()
        for installed_signal in installed_signals:
            loop.remove_signal_handler(installed_signal)
        await runtime.shutdown()
        logger.info("process stopped mode=%s", mode.name)
    if failure is not None:
        raise failure


def _dashboard_server(runtime: AuroraRuntime) -> uvicorn.Server:
    dashboard = runtime.configuration.dashboard
    return uvicorn.Server(
        uvicorn.Config(
            create_app(runtime),
            host=dashboard.host,
            port=dashboard.port,
            log_level=runtime.configuration.logging_level.lower(),
        )
    )


def _install_stop_handlers(stop: asyncio.Event) -> tuple[signal.Signals, ...]:
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for candidate in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(candidate, stop.set)
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(candidate)
    return tuple(installed)
