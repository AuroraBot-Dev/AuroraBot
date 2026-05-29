from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

from src.brain.kernel.circuit import Circuit
from src.brain.kernel.node_factory import build_circuit
from src.brain.nodes import run_event_bridge
from src.config import Config
from src.platform.app_config import app_startup, enabled_app_names, load_apps_config
from src.platform.app_discovery import discover_apps, instantiate_app
from src.platform.application_host import ApplicationHost
from src.platform.contracts import CommandSpec
from src.platform.loop import run_app_loop
from src.utils.log_utils import get_logger

logger = get_logger("Runtime")

_BUILTIN_CONSOLE_SEND_MESSAGE = "im.polaris.console.send_message"


async def _console_print(*, text: str) -> None:
    print("\nBot: " + text + "\n")


def _register_builtin_commands(host: ApplicationHost) -> None:
    if _BUILTIN_CONSOLE_SEND_MESSAGE in host.list_commands():
        return
    host.register_command(
        CommandSpec(
            name=_BUILTIN_CONSOLE_SEND_MESSAGE,
            description="发送消息到本地控制台",
            parameters_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要发送的消息文本"}
                },
                "required": ["text"],
            },
            returns_schema={"type": "object", "properties": {}},
            handler=_console_print,
        )
    )


@dataclass(slots=True)
class RuntimeState:
    host: ApplicationHost
    stop_event: asyncio.Event
    circuit: Circuit | None = None
    app_task: asyncio.Task[None] | None = None
    bridge_task: asyncio.Task[None] | None = None


async def register_selected_apps(
    host: ApplicationHost,
    names: list[str],
    apps_config: dict[str, dict[str, Any]],
) -> None:
    discovered = discover_apps()
    for name in names:
        if name not in discovered:
            raise KeyError(f"Unknown application: {name}")
        await host.register(instantiate_app(name, app_startup(apps_config, name)))


async def register_enabled_apps(host: ApplicationHost) -> dict[str, dict[str, Any]]:
    Config.ensure_dirs()
    apps_config = load_apps_config()
    await register_selected_apps(host, enabled_app_names(apps_config), apps_config)
    return apps_config


async def start_runtime(host: ApplicationHost) -> RuntimeState:
    await register_enabled_apps(host)
    state = RuntimeState(host=host, stop_event=asyncio.Event())
    return await start_runtime_components(state)


async def start_runtime_components(state: RuntimeState) -> RuntimeState:
    _register_builtin_commands(state.host)
    if Config.RUN_MODE in ["app", "application", "dev", "prod"]:
        state.app_task = asyncio.create_task(
            run_app_loop(state.host, state.stop_event, Config.APP_FRAME_INTERVAL)
        )

    if Config.RUN_MODE in ["agent", "core", "dev", "prod"]:
        state.circuit = build_circuit(state.host)
        await state.circuit.start()
        state.bridge_task = asyncio.create_task(
            run_event_bridge(
                state.host,
                state.circuit,
                state.stop_event,
                interval=Config.HEARTBEAT_INTERVAL,
            )
        )

    return state


async def restart_runtime_components(
    state: RuntimeState,
    *,
    start_app_loop: bool,
    start_bridge: bool,
) -> RuntimeState:
    _register_builtin_commands(state.host)
    if start_app_loop:
        state.app_task = asyncio.create_task(
            run_app_loop(state.host, state.stop_event, Config.APP_FRAME_INTERVAL)
        )
    else:
        state.app_task = None

    if state.circuit is not None and not state.circuit.is_running:
        await state.circuit.start()

    if start_bridge and state.circuit is not None:
        state.bridge_task = asyncio.create_task(
            run_event_bridge(
                state.host,
                state.circuit,
                state.stop_event,
                interval=Config.HEARTBEAT_INTERVAL,
            )
        )
    else:
        state.bridge_task = None

    return state


async def stop_runtime_components(state: RuntimeState) -> RuntimeState:
    if state.bridge_task is not None:
        state.bridge_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.bridge_task
    state.bridge_task = None

    if state.circuit is not None and state.circuit.is_running:
        await state.circuit.stop()

    if state.app_task is not None:
        state.app_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.app_task
    state.app_task = None
    return state


async def shutdown_runtime(state: RuntimeState) -> None:
    state.stop_event.set()
    await stop_runtime_components(state)
    await state.host.stop_all()
    logger.info("所有循环已中止")
