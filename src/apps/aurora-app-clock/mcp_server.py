"""Clock MCP Server —— 通过 stdio 与 AuroraBot Platform 通信。

提供时钟、闹钟、定时器等工具。
所有日志输出走 stderr，stdout 只输出 MCP JSON-RPC 消息。

由于 App 目录名 ``aurora-app-clock`` 含横线，无法以 ``-m`` 方式运行，
通过 ``sys.path`` 添加父目录后直接 import service。

暴露工具::

    get_current_time
    set_alarm
    set_timer
    start_heartbeat
    sleep
    list_alarms
    cancel_alarm
"""

from __future__ import annotations

import sys
from pathlib import Path

# 仅将项目根目录加入 sys.path；将 src/ 本身加入会遮蔽标准库 platform。
_parent = Path(__file__).resolve().parent.parent.parent.parent
_app_dir = Path(__file__).resolve().parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from service import ClockService  # type: ignore[import-untyped]

from src.utils.logging import get_logger

logger = get_logger("aurora-app-clock.mcp")

mcp = FastMCP("Clock")


@mcp.tool("get_current_time")
def get_current_time(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """获取当前时间。

    Args:
        fmt: strftime 格式字符串。

    Returns:
        格式化后的当前时间。
    """
    logger.debug("get_current_time called custom_format=%s", fmt is not None)
    return ClockService.get_current_time(fmt)


@mcp.tool("set_alarm")
async def set_alarm(ctx: Context, time_str: str, label: str = "") -> dict[str, Any]:
    """设置闹钟。

    Args:
        time_str: 闹钟时间（如 ``"08:00"``）。
        label: 闹钟标签。

    Returns:
        闹钟信息。
    """
    logger.debug("set_alarm called label_length=%d", len(label))
    await ClockService.initialize(_notifier(ctx))
    return await ClockService.set_alarm(time_str, label)


@mcp.tool("set_timer")
async def set_timer(ctx: Context, seconds: int, label: str = "") -> dict[str, Any]:
    """设置定时器。

    Args:
        seconds: 倒计时秒数。
        label: 定时器标签。

    Returns:
        定时器信息。
    """
    logger.debug("set_timer called label_length=%d", len(label))
    await ClockService.initialize(_notifier(ctx))
    return await ClockService.set_timer(seconds, label)


@mcp.tool("start_heartbeat")
async def start_heartbeat(ctx: Context) -> dict[str, Any]:
    """启动或恢复内建自主心跳。

    此工具由 Aurora 的 MCP Platform 在 Clock 启动后调用。已有心跳会被恢复而不是重置。
    """
    await ClockService.initialize(_notifier(ctx))
    return ClockService.start_heartbeat()


@mcp.tool("sleep")
async def sleep(ctx: Context, seconds: int) -> dict[str, Any]:
    """把下一次自主心跳安排在一段安静休息后。

    实际时长会限制在部署配置的心跳边界内；普通闹钟和外部消息仍可提前带来新的事实。
    """
    await ClockService.initialize(_notifier(ctx))
    return ClockService.sleep(seconds)


@mcp.tool("list_alarms")
def list_alarms() -> list[dict[str, Any]]:
    """列出所有闹钟和定时器。

    Returns:
        闹钟/定时器列表。
    """
    logger.debug("list_alarms called")
    return ClockService.list_alarms()


@mcp.tool("cancel_alarm")
def cancel_alarm(alarm_id: str) -> bool:
    """取消闹钟或定时器。

    Args:
        alarm_id: 闹钟/定时器 ID。

    Returns:
        是否成功取消。
    """
    logger.debug("cancel_alarm called: alarm_id=%r", alarm_id)
    return ClockService.cancel_alarm(alarm_id)


def _notifier(ctx: Context):
    async def send(event_type: str, data: dict[str, Any]) -> None:
        await ctx.session.send_log_message(
            level="info",
            logger="aurora/event",
            data={"type": event_type, "data": data},
        )

    return send


if __name__ == "__main__":
    logger.info("Starting Clock MCP server (stdio transport)")
    mcp.run(transport="stdio")
