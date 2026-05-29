# ============================================
# 控制台命令处理
# ============================================

from __future__ import annotations
import argparse
import asyncio
from dataclasses import dataclass
import importlib
import json
import os
import shlex
import signal
import sys
import threading
from types import ModuleType
from typing import Awaitable, Callable

from src.brain.memory import MemoryContext, memory_manager
from src.brain.runtime import (
    RuntimeState,
    restart_runtime_components,
    shutdown_runtime,
    stop_runtime_components,
)
from src.platform.contracts import AppEvent
from src.utils.json_utils import json_ready, parse_json_or_yaml_object
from src.utils.log_utils import get_logger

logger = get_logger("Localhost")


# ============================================
# 命令注册常量
# ============================================


# -- 帮助命令 --
HELP_COMMANDS = ("/help", "/h")

# -- 控制命令 --
RELOAD_COMMANDS = ("/reload", "/r")
STOP_COMMANDS = ("/stop", "/quit", "/exit", "/q")

# -- 内建发送消息命令 --
SAY_COMMANDS = ("/say", "/s")

# -- 事件/应用/指令/事件命令 --
EVENT_COMMANDS = ("/event", "/e")
INVOKE_COMMANDS = ("/invoke", "/i")

APPS_COMMANDS = ("/apps", "/A")
COMMANDS_COMMANDS = ("/commands", "/C")
EVENTS_COMMANDS = ("/events", "/E")

# -- 记忆测试命令 --
MEMTEST_COMMANDS = ("/memtest", "/mt")

_SELF_MODULE = __name__

_MODULES_TO_RELOAD: list[str] = [
    "src.platform.app_config",
    "src.platform.app_discovery",
    "src.utils.json_utils",
    "src.brain.ai.gateway",
    "src.brain.prompts",
    "src.brain.kernel.base",
    "src.brain.kernel.circuit",
    "src.brain.kernel.state_store",
    "src.brain.nodes.agents.polaris_agent",
    "src.brain.nodes.agents",
    "src.brain.nodes.event_bridge",
    "src.brain.nodes",
    "src.brain.kernel.node_factory",
    _SELF_MODULE,
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


# ============================================
# 帮助命令
# ============================================


async def _handle_help_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:

    specs = list(_console_commands())
    usage_width = max((len(spec.usage) for spec in specs), default=0)
    gap = 2
    all_commands = "\n"
    for spec in specs:
        all_commands += (
            f"{spec.usage.ljust(usage_width)}{' ' * gap}{spec.description}\n"
        )
    logger.info(all_commands)
    return runtime


# ============================================
# 控制命令
# ============================================


def _parse_control_command(raw: str) -> ParsedConsoleCommand | None:
    command_line = raw.strip()
    if not command_line:
        return None

    try:
        tokens = shlex.split(command_line)
    except ValueError:
        logger.warning(f"控制台命令解析失败: {command_line}")
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


def _reload_modules() -> None:
    importlib.invalidate_caches()
    names = [name for name in _MODULES_TO_RELOAD if name != _SELF_MODULE]
    if _SELF_MODULE in _MODULES_TO_RELOAD:
        names.append(_SELF_MODULE)
    for name in names:
        _reload_module(name)


def _reload_package_modules(package_name: str) -> None:
    names = [
        name
        for name in sys.modules
        if name == package_name or name.startswith(f"{package_name}.")
    ]
    for name in sorted(names, key=lambda item: (item.count("."), item), reverse=True):
        _reload_module(name)


async def reload_brain(*, runtime: RuntimeState) -> RuntimeState:
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


async def handle_control_command(
    raw: str,
    *,
    runtime: RuntimeState | None,
    lock: asyncio.Lock,
) -> RuntimeState | None:
    parsed = _parse_control_command(raw)
    if parsed is None:
        text = raw.strip()
        if not text:
            return runtime
        say_spec = next(
            spec for spec in _console_commands() if spec.names == SAY_COMMANDS
        )
        parsed = ParsedConsoleCommand(
            raw=raw,
            name=SAY_COMMANDS[0],
            args=(text,),
            raw_args=text,
            spec=say_spec,
        )
    if runtime is None:
        logger.warning("控制命令已忽略: runtime 尚未初始化")
        return runtime
    if lock.locked():
        logger.info("已有控制任务在执行，忽略重复指令")
        return runtime

    logger.info(f"执行指令: {parsed.name}")
    async with lock:
        try:
            return await parsed.spec.handler(runtime, parsed)
        except HotReloadError as exc:
            logger.exception("热重载失败，已回滚旧运行时")
            return exc.runtime
        except Exception:
            logger.exception(f"指令执行失败: {parsed.name}")
            return runtime


# -- 热重载命令 --
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
    names = [name for name in _MODULES_TO_RELOAD if name != _SELF_MODULE]
    if _SELF_MODULE in _MODULES_TO_RELOAD:
        names.append(_SELF_MODULE)
    for name in names:
        _reload_module(name)


def _reload_package_modules(package_name: str) -> None:
    names = [
        name
        for name in sys.modules
        if name == package_name or name.startswith(f"{package_name}.")
    ]
    for name in sorted(names, key=lambda item: (item.count("."), item), reverse=True):
        _reload_module(name)


async def reload_brain(*, runtime: RuntimeState) -> RuntimeState:
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


async def _handle_reload_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    return await reload_brain(runtime=runtime)


# -- 停止命令 --


async def _handle_stop_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> None:
    await stop_process(runtime=runtime)
    return None


def _request_process_exit() -> None:
    try:
        signal.raise_signal(signal.SIGINT)
    except AttributeError:
        os.kill(os.getpid(), signal.SIGINT)


async def stop_process(*, runtime: RuntimeState) -> None:
    logger.info("收到停止请求，准备关闭当前进程")
    await shutdown_runtime(runtime)
    sys.stdout.flush()
    sys.stderr.flush()
    _request_process_exit()


# ============================================
# 内建发送消息命令
# ============================================


async def _handle_say_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    message = " ".join(parsed.args).strip()
    if not message:
        logger.warning(f"控制台命令 {parsed.name} 需要提供消息文本")
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
    logger.info(f"已注入消息: {message}")
    return runtime


# ============================================
# 事件/指令/应用命令
# ============================================


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


def _build_commands_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/commands")
    parser.add_argument("--detail")
    return parser


# -- 事件命令 --
async def _handle_event_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_event_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    payload = parse_json_or_yaml_object(args.payload)
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
        f"已注入事件 type={args.event_type} source={args.source} session={args.session_id}",
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
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
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
        f"当前事件队列:\n"
        + json.dumps(
            {"events": [event.to_dict() for event in events]},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime


# -- 指令命令 --
async def _handle_invoke_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_invoke_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    payload = parse_json_or_yaml_object(args.payload)
    result = await runtime.host.invoke_command(args.command_name, **payload)
    logger.info(
        f"命令执行结果 {args.command_name}:\n"
        + json.dumps(
            {"result": json_ready(result)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return runtime


async def _handle_commands_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_commands_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    if not args.detail:
        payload = {"commands": runtime.host.list_commands()}
    else:
        specs = runtime.host.list_command_specs()
        if args.detail == "all":
            payload = {
                "commands": [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters_schema": spec.parameters_schema,
                        "returns_schema": spec.returns_schema,
                    }
                    for spec in specs
                ]
            }
        else:
            target = next((spec for spec in specs if spec.name == args.detail), None)
            if target is None:
                logger.warning(f"命令 {parsed.name} 未找到: {args.detail}")
                return runtime
            payload = {
                "command": {
                    "name": target.name,
                    "description": target.description,
                    "parameters_schema": target.parameters_schema,
                    "returns_schema": target.returns_schema,
                }
            }
    logger.info(
        f"可用命令:\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime


# -- 应用命令 --
async def _handle_apps_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    logger.info(
        f"已加载应用:\n"
        + json.dumps(
            {"apps": runtime.host.list_apps()},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime


# -- 记忆测试命令 --
def _build_memtest_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/memtest")
    parser.add_argument("subcommand", nargs="?", default="help")
    parser.add_argument("args", nargs="*", default=[])
    return parser


async def _handle_memtest_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_memtest_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    sub = (args.subcommand or "help").strip().lower()
    raw_args = " ".join(args.args) if args.args else ""

    if sub == "help":
        logger.info(
            "\n  /memtest query <text>        检索记忆上下文\n"
            "  /memtest record <text>       记录一条用户交互\n"
            "  /memtest context [--user-id ID]  查看当前记忆上下文\n"
        )
        return runtime

    if sub == "context":
        user_id = "localhost"
        ctx: MemoryContext = memory_manager.retrieve_context(
            current_query="__context_snapshot__", user_id=user_id
        )
        prompt_text = ctx.to_prompt_text() if ctx else "(空)"
        logger.info(f"\n--- 记忆上下文 (user={user_id}) ---\n{prompt_text}")
        return runtime

    if sub == "query":
        if not raw_args:
            logger.warning("query 需要提供查询文本")
            return runtime
        user_id = "localhost"
        ctx = memory_manager.retrieve_context(current_query=raw_args, user_id=user_id)
        prompt_text = ctx.to_prompt_text() if ctx else "(无匹配记忆)"
        logger.info(f"\n--- 记忆检索结果 (query={raw_args}) ---\n{prompt_text}")
        return runtime

    if sub == "record":
        if not raw_args:
            logger.warning("record 需要提供记录文本")
            return runtime
        memory_manager.process_interaction(
            content=raw_args, role="user", user_id="localhost"
        )
        logger.info(f"已记录交互: {raw_args}")
        return runtime

    logger.warning(f"未知子命令: {sub}，使用 /memtest help 查看用法")
    return runtime


# ============================================
# 命令解析器
# ============================================


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
            usage="/commands [--detail all|<name>]",
            description="列出当前可调用命令. 指定命令名展开 schema.",
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
        ConsoleCommand(
            names=MEMTEST_COMMANDS,
            usage="/memtest <query|record|context> [args...]",
            description="记忆系统交互测试：query 检索 / record 记录 / context 查看",
            handler=_handle_memtest_command,
        ),
    )


# ============================================
# 控制台命令循环
# ============================================


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
    logger.info(f"控制台命令监听已启动，使用 `/help` 查看支持的命令")
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
