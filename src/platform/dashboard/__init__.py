"""Dashboard 平台公开 API。

导出自描述 ``_create``，组合根通过统一协议完成创建、工具绑定与任务调度。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.platform.dashboard.adapter import (
    DASHBOARD_SEND_CAPABILITY,
    DASHBOARD_SEND_DESCRIPTOR,
    DashboardPlatform,
)
from src.platform.dashboard.api import create_app
from src.platform.dashboard.server import SignalSafeServer, _LifespanSafeApp
from src.platform.dashboard.service import ChatError, ChatService

if TYPE_CHECKING:
    from src.contracts.configuration import DashboardConfig
    from src.platform import PlatformHandle

__all__ = [
    "DASHBOARD_SEND_CAPABILITY",
    "DASHBOARD_SEND_DESCRIPTOR",
    "ChatError",
    "ChatService",
    "DashboardPlatform",
    "create_app",
]


async def _create(_config: object, runtime: object) -> "PlatformHandle":
    """创建 Dashboard 平台句柄，含聊天服务、平台适配器与 HTTP 服务器。"""
    from src.contracts.tool import ToolExecutorBinding
    from src.platform import PlatformHandle

    config = getattr(runtime, "configuration")  # noqa: B009  # type: ignore[union-attr]
    dashboard_cfg: "DashboardConfig" = config.dashboard  # type: ignore[union-attr]
    chat = ChatService(dashboard_cfg, config)  # type: ignore[arg-type]
    await chat.start()
    dash = DashboardPlatform(chat)
    server = _build_server(config, chat)

    return PlatformHandle(
        bindings=(
            ToolExecutorBinding(
                DASHBOARD_SEND_DESCRIPTOR,
                dash,
                source_app="platform.dashboard",
                source_instance="local",
                recovery=dash,
            ),
        ),
        http_server=server,
        spawn=lambda _rt, _stop: asyncio.ensure_future(server.serve()),
    )


def _build_server(config: object, chat: ChatService) -> "SignalSafeServer":
    """构建带禁用信号捕获的 uvicorn HTTP 服务器。"""
    import uvicorn

    cfg: "DashboardConfig" = config.dashboard  # type: ignore[union-attr]
    uvc = uvicorn.Config(
        _LifespanSafeApp(
            create_app(
                chat,
                config,  # type: ignore[arg-type]
                cfg,
                profile=config.runtime.profile,  # type: ignore[union-attr]
            )
        ),
        host=cfg.host,
        port=cfg.port,
        log_level=config.logging_level.lower(),  # type: ignore[union-attr]
        log_config=None,
        access_log=False,
    )
    return SignalSafeServer(uvc)
