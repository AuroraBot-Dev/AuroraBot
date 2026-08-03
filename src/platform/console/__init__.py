"""Console 平台公开 API。

导出自描述 ``_create``，组合根通过统一协议完成创建、工具绑定与任务调度。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.platform.console.adapter import (
    CONSOLE_SEND_CAPABILITY,
    CONSOLE_SEND_DESCRIPTOR,
    ConsolePlatform,
)
from src.platform.console.shell import run_console

if TYPE_CHECKING:
    from src.platform import PlatformHandle

__all__ = [
    "CONSOLE_SEND_CAPABILITY",
    "CONSOLE_SEND_DESCRIPTOR",
    "ConsolePlatform",
]


async def _create(_config: object, runtime: object) -> "PlatformHandle":
    """创建 Console 平台句柄。"""
    from src.contracts.tool import ToolExecutorBinding
    from src.platform import PlatformHandle

    db_path = getattr(runtime, "configuration").storage.console / "runtime.sqlite3"  # noqa: B009  # type: ignore[attr-defined,union-attr]
    console = ConsolePlatform(db_path)
    return PlatformHandle(
        bindings=(
            ToolExecutorBinding(
                CONSOLE_SEND_DESCRIPTOR,
                console,
                source_app="platform.console",
                source_instance="local",
                recovery=console,
            ),
        ),
        cleanup=console.close,
        spawn=lambda _rt, stop: asyncio.ensure_future(run_console(_rt, console, stop_event=stop)),
    )
