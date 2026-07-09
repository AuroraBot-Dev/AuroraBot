"""控制台核心命令处理 —— /help、/reload、/stop、/tools、/apps 的实现。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.registry import ParsedConsoleCommand, _console_commands
from src.localhost.reloader import reload_runtime, stop_process
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.runtime import RuntimeState

logger = get_logger("Localhost")


async def _handle_help_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    specs = list(_console_commands())
    usage_width = max((len(spec.usage) for spec in specs), default=0)
    gap = 2
    all_commands = "\n"
    for spec in specs:
        all_commands += f"{spec.usage.ljust(usage_width)}{' ' * gap}{spec.description}\n"
    logger.debug(all_commands)
    return runtime


async def _handle_reload_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    return await reload_runtime(runtime=runtime)


async def _handle_stop_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> None:
    await stop_process(runtime=runtime)


async def _handle_tools_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    """列出当前所有可用 MCP 工具。"""
    tools = runtime.client_manager.list_all_tools()
    payload: dict[str, object] = {}
    for server_key, server_tools in tools.items():
        tool_list = []
        for tool in server_tools:
            name = getattr(tool, "name", "")
            description = getattr(tool, "description", "")
            tool_list.append({"name": f"{server_key}.{name}", "description": description})
        payload[server_key] = tool_list

    logger.debug(
        "可用 MCP 工具:\n%s",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    return runtime


async def _handle_apps_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    """列出 MCP Server 健康状态。"""
    report = runtime.server_kit.health_report()
    logger.debug(
        "MCP Server 状态:\n%s",
        json.dumps(report, ensure_ascii=False, indent=2),
    )
    return runtime
