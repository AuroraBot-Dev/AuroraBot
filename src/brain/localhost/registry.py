from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.brain.runtime import RuntimeState

HELP_COMMANDS = ("/help", "/h")
RELOAD_COMMANDS = ("/reload", "/r")
STOP_COMMANDS = ("/stop", "/quit", "/exit", "/q")
SAY_COMMANDS = ("/say", "/s")
EVENT_COMMANDS = ("/event", "/e", "/emit")
INVOKE_COMMANDS = ("/invoke", "/i")
TOOLS_COMMANDS = ("/tools", "/T")
APPS_COMMANDS = ("/apps", "/A")
MEMTEST_COMMANDS = ("/memtest", "/mt")
SELF_STREAM_COMMANDS = ("/stream",)
SELF_STATE_COMMANDS = ("/state",)
SELF_MEMORIES_COMMANDS = ("/memories", "/mem")


@dataclass(frozen=True, slots=True)
class ConsoleCommand:
    names: tuple[str, ...]
    usage: str
    description: str
    handler: Callable[[RuntimeState, "ParsedConsoleCommand"], Awaitable[RuntimeState | None]]


@dataclass(frozen=True, slots=True)
class ParsedConsoleCommand:
    raw: str
    name: str
    args: tuple[str, ...]
    raw_args: str
    spec: ConsoleCommand


def _console_commands() -> tuple[ConsoleCommand, ...]:
    from src.brain.localhost.commands.core import (
        _handle_apps_command,
        _handle_help_command,
        _handle_reload_command,
        _handle_stop_command,
        _handle_tools_command,
    )
    from src.brain.localhost.commands.emit import _handle_event_command
    from src.brain.localhost.commands.invoke import _handle_invoke_command
    from src.brain.localhost.commands.memtest import _handle_memtest_command
    from src.brain.localhost.commands.say import _handle_say_command
    from src.brain.localhost.commands.self_cli import (
        _handle_memories_command,
        _handle_state_command,
        _handle_stream_command,
    )

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
            description="列出 MCP Server 健康状态",
            handler=_handle_apps_command,
        ),
        ConsoleCommand(
            names=TOOLS_COMMANDS,
            usage="/tools",
            description="列出当前所有可用 MCP 工具",
            handler=_handle_tools_command,
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
        ConsoleCommand(
            names=SELF_STREAM_COMMANDS,
            usage="/stream [lines]",
            description="查看她最近的自我之流 (now.md)",
            handler=_handle_stream_command,
        ),
        ConsoleCommand(
            names=SELF_STATE_COMMANDS,
            usage="/state",
            description="查看她当前的自我状态",
            handler=_handle_state_command,
        ),
        ConsoleCommand(
            names=SELF_MEMORIES_COMMANDS,
            usage="/memories [name]",
            description="列出或查看她的持久记忆",
            handler=_handle_memories_command,
        ),
    )
