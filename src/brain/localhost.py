# ============================================
# 控制台命令处理
# ============================================

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import importlib
import json
import os
import shlex
import signal
import sys
import threading
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Awaitable, Callable

import yaml

from src.brain.runtime import (
    RuntimeState,
    restart_runtime_components,
    shutdown_runtime,
    stop_runtime_components,
)
from src.platform.contracts import AppEvent
from src.utils.log_utils import get_logger

logger = get_logger("Localhost")

HELP_COMMANDS = ("/help", "/h")
RELOAD_COMMANDS = ("/reload", "/r")
STOP_COMMANDS = ("/stop", "/quit", "/exit")
SAY_COMMANDS = ("/say", "/s")
EVENT_COMMANDS = ("/event", "/e")
INVOKE_COMMANDS = ("/invoke", "/i")
APPS_COMMANDS = ("/apps", "/a")
COMMANDS_COMMANDS = ("/commands", "/c")
EVENTS_COMMANDS = ("/events", "/E")

_MODULES_TO_RELOAD: list[str] = [
    "src.platform.app_config",
    "src.platform.app_discovery",
    "src.utils.json_utils",
    "src.brain.ai.llm_gate",
    "src.brain.prompts",
    "src.brain.kernel.base",
    "src.brain.kernel.circuit",
    "src.brain.kernel.state_store",
    "src.brain.nodes.agents.polaris_agent",
    "src.brain.nodes.agents",
    "src.brain.nodes.event_bridge",
    "src.brain.nodes",
    "src.brain.kernel.node_factory",
]

_MODULES_TO_SKIP_RELOAD: dict[str, str] = {
    "src.config": "该模块由 NoneBot 插件系统管理",
    "src.main": "该模块由 NoneBot 插件系统管理",
}


class HotReloadError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        runtime: RuntimeState,
    ) -> None:
        super().__init__(message)
        self.runtime = runtime


@dataclass(frozen=True, slots=True)
class ConsoleCommand:
    names: tuple[str, ...]
    usage: str
    description: str
    handler: Callable[
        [RuntimeState, "ParsedConsoleCommand"], Awaitable[RuntimeState | None]
    ]


@dataclass(frozen=True, slots=True)
class ParsedConsoleCommand:
    raw: str
    name: str
    args: tuple[str, ...]
    raw_args: str
    spec: ConsoleCommand


class _ConsoleArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


async def handle_control_command(
    raw: str,
    *,
    runtime: RuntimeState | None,
    lock: asyncio.Lock,
) -> RuntimeState | None:
    parsed = _parse_control_command(raw)
    if parsed is None:
        return runtime
    if runtime is None:
        logger.warning("控制命令已忽略: runtime 尚未初始化")
        return runtime
    if lock.locked():
        logger.info("已有控制任务在执行，忽略重复指令")
        return runtime

    logger.info(f"收到控制台指令: {parsed.name}")
    async with lock:
        try:
            return await parsed.spec.handler(runtime, parsed)
        except HotReloadError as exc:
            logger.exception("热重载失败，已回滚旧运行时")
            return exc.runtime
        except Exception:
            logger.exception(f"控制台命令执行失败: {parsed.name}")
            return runtime

    return runtime


async def _handle_reload_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    return await reload_brain(runtime=runtime)


async def _handle_stop_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> None:
    await stop_process(runtime=runtime)
    return None


async def _handle_help_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    for spec in _console_commands():
        logger.info("%s - %s", spec.usage, spec.description)
    return runtime


async def _handle_say_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    message = " ".join(parsed.args).strip()
    if not message:
        logger.warning("控制台命令 `%s` 需要提供消息文本", parsed.name)
        return runtime

    session_id = "private:localhost"
    runtime.host.emit_event(
        AppEvent(
            source="manual.console",
            type="message.received",
            session_id=session_id,
            summary=message,
            payload={
                "session_id": session_id,
                "text": message,
                "user_id": "localhost",
                "is_group": False,
                "group_id": None,
                "bot_id": "console",
            },
        )
    )
    logger.info("已注入控制台消息: %s", message)
    return runtime


async def _handle_event_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_event_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning("命令 `%s` 参数错误: %s", parsed.name, exc)
        return runtime

    payload = _parse_json(args.payload)
    runtime.host.emit_event(
        AppEvent(
            source=args.source,
            type=args.event_type,
            session_id=args.session_id,
            summary=args.summary or str(payload.get("text", "")),
            payload=payload,
        )
    )
    logger.info(
        "已注入事件 type=%s source=%s session=%s",
        args.event_type,
        args.source,
        args.session_id,
    )
    return runtime


async def _handle_invoke_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_invoke_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning("命令 `%s` 参数错误: %s", parsed.name, exc)
        return runtime

    payload = _parse_json(args.payload)
    result = await runtime.host.invoke_command(args.command_name, **payload)
    logger.info(
        "命令执行结果 %s:\n%s",
        args.command_name,
        json.dumps({"result": _json_ready(result)}, ensure_ascii=False, indent=2),
    )
    return runtime


async def _handle_apps_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    logger.info(
        "已加载应用:\n%s",
        json.dumps({"apps": runtime.host.list_apps()}, ensure_ascii=False, indent=2),
    )
    return runtime


async def _handle_commands_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    logger.info(
        "可用命令:\n%s",
        json.dumps(
            {"commands": runtime.host.list_commands()},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime


async def _handle_events_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_events_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning("命令 `%s` 参数错误: %s", parsed.name, exc)
        return runtime

    events = (
        runtime.host.drain_events(limit=args.limit)
        if args.drain
        else (
            runtime.host.peek_events()[: args.limit]
            if args.limit is not None
            else runtime.host.peek_events()
        )
    )
    logger.info(
        "当前事件队列:\n%s",
        json.dumps(
            {"events": [event.to_dict() for event in events]},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime


def _console_commands() -> tuple[ConsoleCommand, ...]:
    return (
        ConsoleCommand(
            names=HELP_COMMANDS,
            usage="/help",
            description="打印控制台可用命令列表",
            handler=_handle_help_command,
        ),
        ConsoleCommand(
            names=RELOAD_COMMANDS,
            usage="/reload",
            description="热重载当前脑回路与应用实例",
            handler=_handle_reload_command,
        ),
        ConsoleCommand(
            names=SAY_COMMANDS,
            usage="/say <message>",
            description="向应用宿主注入一条本地消息事件",
            handler=_handle_say_command,
        ),
        ConsoleCommand(
            names=EVENT_COMMANDS,
            usage="/event <type> [--source SRC] [--session ID] [--summary TEXT] [--payload JSON]",
            description="注入任意标准应用事件",
            handler=_handle_event_command,
        ),
        ConsoleCommand(
            names=INVOKE_COMMANDS,
            usage="/invoke <command> [--payload JSON]",
            description="直接调用应用命令并打印结果",
            handler=_handle_invoke_command,
        ),
        ConsoleCommand(
            names=APPS_COMMANDS,
            usage="/apps",
            description="列出当前已加载应用",
            handler=_handle_apps_command,
        ),
        ConsoleCommand(
            names=COMMANDS_COMMANDS,
            usage="/commands",
            description="列出当前可调用命令",
            handler=_handle_commands_command,
        ),
        ConsoleCommand(
            names=EVENTS_COMMANDS,
            usage="/events [--drain] [--limit N]",
            description="查看或消费当前事件队列",
            handler=_handle_events_command,
        ),
        ConsoleCommand(
            names=STOP_COMMANDS,
            usage="/stop",
            description="优雅关闭当前进程",
            handler=_handle_stop_command,
        ),
    )


def _parse_control_command(raw: str) -> ParsedConsoleCommand | None:
    command_line = raw.strip()
    if not command_line:
        return None

    try:
        tokens = shlex.split(command_line)
    except ValueError:
        logger.warning("控制台命令解析失败: %s", command_line)
        return None

    if not tokens:
        return None

    name = tokens[0]
    for spec in _console_commands():
        if name in spec.names:
            raw_args = command_line.split(maxsplit=1)[1] if len(tokens) > 1 else ""
            return ParsedConsoleCommand(
                raw=command_line,
                name=name,
                args=tuple(tokens[1:]),
                raw_args=raw_args,
                spec=spec,
            )
    return None


def _console_command_aliases() -> list[str]:
    aliases: list[str] = []
    for spec in _console_commands():
        aliases.extend(spec.names)
    return sorted(aliases)


def _build_event_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/event")
    parser.add_argument("event_type")
    parser.add_argument("--source", default="manual.console")
    parser.add_argument("--session", dest="session_id", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--payload", default="")
    return parser


def _build_invoke_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/invoke")
    parser.add_argument("command_name")
    parser.add_argument("--payload", default="")
    return parser


def _build_events_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/events")
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser


def _parse_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = yaml.safe_load(text)
    return _json_ready(payload) if isinstance(payload, dict) else {}


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _reload_module(name: str) -> None:
    try:
        module = importlib.import_module(name)
        skip_reason = _should_skip_reload(name, module)
        if skip_reason is not None:
            logger.info(f"跳过模块重载 {name}: {skip_reason}")
            return
        importlib.reload(module)
        logger.info(f"已重载模块 {name}")
    except Exception:
        logger.exception(f"重载模块 {name} 失败")
        raise


def _should_skip_reload(name: str, module: ModuleType) -> str | None:
    if name in _MODULES_TO_SKIP_RELOAD:
        return _MODULES_TO_SKIP_RELOAD[name]

    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None)
    if loader is None:
        return None

    loader_module = getattr(loader.__class__, "__module__", "")
    if loader_module.startswith("nonebot.plugin"):
        return "该模块由 NoneBot 插件加载器管理"
    return None


def _reload_modules() -> None:
    importlib.invalidate_caches()
    for name in _MODULES_TO_RELOAD:
        _reload_module(name)


def _reload_package_modules(package_name: str) -> None:
    names = [
        name
        for name in sys.modules
        if name == package_name or name.startswith(f"{package_name}.")
    ]
    for name in sorted(names, key=lambda item: (item.count("."), item), reverse=True):
        _reload_module(name)


async def reload_brain(
    *,
    runtime: RuntimeState,
) -> RuntimeState:
    """热重载脑回路：停止 → 重载模块 → 重建 → 重启。"""
    logger.info("热重载开始 — 冻结运行时...")
    previous_apps = [
        app
        for package in runtime.host.list_apps()
        if (app := runtime.host.get_app(package)) is not None
    ]
    previous_had_app_loop = runtime.app_task is not None
    previous_had_bridge = runtime.bridge_task is not None
    apps_replaced = False

    try:
        await stop_runtime_components(runtime)

        _reload_modules()

        from src.brain.runtime import start_runtime_components
        from src.platform.app_config import (
            app_startup,
            enabled_app_names,
            load_apps_config,
        )
        from src.platform.app_discovery import discover_apps, instantiate_app

        apps_config = load_apps_config()
        discovered = discover_apps()
        enabled_names = [
            name for name in enabled_app_names(apps_config) if name in discovered
        ]
        for app_name in enabled_names:
            _reload_package_modules(f"apps.{app_name}")

        new_apps = [
            instantiate_app(app_name, app_startup(apps_config, app_name))
            for app_name in enabled_names
        ]
        await runtime.host.replace_apps(new_apps)
        apps_replaced = True

        runtime.circuit = None
        runtime.app_task = None
        runtime.bridge_task = None
        await start_runtime_components(runtime)
    except Exception as exc:
        logger.exception("热重载失败，准备回滚到旧运行时")
        try:
            if apps_replaced:
                await runtime.host.replace_apps(previous_apps)
            runtime.app_task = None
            runtime.bridge_task = None
            await restart_runtime_components(
                runtime,
                start_app_loop=previous_had_app_loop,
                start_bridge=previous_had_bridge,
            )
        except Exception:
            logger.exception("热重载回滚失败，运行时可能处于部分可用状态")
        raise HotReloadError(
            "热重载失败，已尝试回滚旧运行时",
            runtime=runtime,
        ) from exc

    logger.info("热重载完成")
    return runtime


async def stop_process(*, runtime: RuntimeState) -> None:
    logger.info("收到停止请求，准备关闭当前进程")
    await shutdown_runtime(runtime)
    sys.stdout.flush()
    sys.stderr.flush()
    _request_process_exit()


async def run_console_control_loop(
    dispatch_command: Callable[[str], Awaitable[None]],
    *,
    readline: Callable[[], str] | None = None,
    idle_delay: float = 0.5,
) -> None:
    read_line = readline or sys.stdin.readline
    loop = asyncio.get_running_loop()
    input_queue: asyncio.Queue[str] = asyncio.Queue()
    stop_event = threading.Event()

    def _reader() -> None:
        while not stop_event.is_set():
            try:
                line = read_line()
            except Exception:
                logger.exception("控制台输入读取失败")
                break

            if line == "":
                if stop_event.wait(idle_delay):
                    break
                continue

            try:
                loop.call_soon_threadsafe(input_queue.put_nowait, line)
            except RuntimeError:
                break

    reader_thread = threading.Thread(
        target=_reader,
        name="console-control-reader",
        daemon=True,
    )
    reader_thread.start()
    logger.info(
        f"控制台命令监听已启动，支持命令: [{', '.join(_console_command_aliases())}]"
    )
    try:
        while True:
            line = await input_queue.get()
            command = line.strip()
            if not command:
                continue

            await dispatch_command(command)
    except asyncio.CancelledError:
        stop_event.set()
        logger.info("控制台命令监听已停止")
        raise


def _request_process_exit() -> None:
    try:
        signal.raise_signal(signal.SIGINT)
    except AttributeError:
        os.kill(os.getpid(), signal.SIGINT)
