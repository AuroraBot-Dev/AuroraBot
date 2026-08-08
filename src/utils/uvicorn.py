"""uvicorn 服务器共享辅助：优雅退出与 lifespan 安全包装。

ops 调试 API 与 Dashboard HTTP 服务器共用同一套停止协议：
组合根统一捕获信号并设置 should_exit，服务器本身不自行接管信号；
lifespan 阶段被强制取消时抑制 CancelledError 日志。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import uvicorn

if TYPE_CHECKING:
    from collections.abc import Generator


class LifespanSafeApp:
    """在 lifespan 阶段抑制 CancelledError traceback 的 ASGI 包装器。

    若关闭因连接挂起而超时被强制取消，孤儿 lifespan 任务会在进程收尾时
    被 asyncio 取消，此处抑制其异常日志。
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            with contextlib.suppress(asyncio.CancelledError):
                await self._app(scope, receive, send)
        else:
            await self._app(scope, receive, send)


class SignalSafeServer(uvicorn.Server):
    """禁止 uvicorn 自行捕获进程信号，由组合根统一管理停止流程。"""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, Any, None]:  # type: ignore[no-untyped-def]
        yield
