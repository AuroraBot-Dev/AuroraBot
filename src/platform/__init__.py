"""RFC 0107 — 平台归一化与环境效果执行适配器。

每个平台子包通过统一协议自描述：导出 ``_create`` 函数，
组合根无需知晓具体平台实现即可完成创建、工具绑定与任务调度。

Console / Dashboard / MCP adapter，Tool 注册，ToolOutcome 与心跳。
只依赖 contracts 窄端口，不得直接操作 engine 或 localhost。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.contracts.tool import ToolExecutorBinding


@dataclass(slots=True)
class PlatformHandle:
    """平台创建并启动后的运行时句柄，由组合根统一管理。"""

    bindings: tuple[ToolExecutorBinding, ...] = ()
    cleanup: Callable[..., Any] | None = None
    spawn: Callable[..., Any] | None = None
    http_server: object = None
