"""Dashboard 平台公开 API。

导出自描述 ``_create``，组合根通过统一协议完成创建、工具绑定与任务调度。
浏览器打开是平台自身的环境效果，由平台在服务就绪后执行。
"""

from __future__ import annotations

import asyncio
import webbrowser
from functools import partial
from typing import TYPE_CHECKING

from src.platform.dashboard.adapter import (
    DASHBOARD_SEND_CAPABILITY,
    DASHBOARD_SEND_DESCRIPTOR,
    DashboardPlatform,
)
from src.platform.dashboard.api import create_app
from src.platform.dashboard.service import ChatError, ChatService
from src.utils.uvicorn import (
    LifespanSafeApp,
    SignalSafeServer,
)

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig, DashboardConfig
    from src.contracts.platform import PlatformHandle, PlatformRuntimePort

__all__ = [
    "DASHBOARD_SEND_CAPABILITY",
    "DASHBOARD_SEND_DESCRIPTOR",
    "ChatError",
    "ChatService",
    "DashboardPlatform",
    "create_app",
]


async def _create(config: "AuroraConfig", runtime: "PlatformRuntimePort") -> "PlatformHandle":
    """创建 Dashboard 平台句柄，含聊天服务、平台适配器与 HTTP 服务器。"""
    from src.contracts.platform import PlatformHandle
    from src.contracts.tool import ToolExecutorBinding

    dashboard_cfg = config.dashboard
    chat = ChatService(dashboard_cfg, runtime)
    await chat.start()
    dash = DashboardPlatform(chat)
    server = _build_server(config, runtime, chat)
    background = (
        None
        if not config.preference.dashboard.open_browser
        else partial(_open_browser_when_ready, server, dashboard_cfg)
    )

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
        server=server,
        background=background,
    )


async def _open_browser_when_ready(
    server: "SignalSafeServer", configuration: "DashboardConfig", stop: asyncio.Event
) -> None:
    """服务器就绪后打开 Dashboard，并存活至统一停止。"""
    while not server.started:
        if server.should_exit or stop.is_set():
            return
        await asyncio.sleep(0.01)
    if server.should_exit or stop.is_set():
        return
    await asyncio.to_thread(_open_dashboard_browser, configuration)
    await stop.wait()


def _open_dashboard_browser(configuration: "DashboardConfig") -> None:
    """在默认浏览器中打开 Dashboard 地址。"""
    host = "127.0.0.1" if configuration.host in {"0.0.0.0", "::"} else configuration.host
    if ":" in host:
        host = f"[{host}]"
    webbrowser.open(f"http://{host}:{configuration.port}")


def _build_server(config: "AuroraConfig", runtime: "PlatformRuntimePort", chat: ChatService) -> "SignalSafeServer":
    """构建带禁用信号捕获的 uvicorn HTTP 服务器。"""
    import uvicorn

    cfg = config.dashboard
    uvc = uvicorn.Config(
        LifespanSafeApp(
            create_app(
                chat,
                runtime,
                cfg,
                profile=config.runtime.profile,
            )
        ),
        host=cfg.host,
        port=cfg.port,
        log_level=config.logging_level.lower(),
        log_config=None,
        access_log=False,
    )
    return SignalSafeServer(uvc)
