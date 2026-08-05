"""Dashboard uvicorn 服务器辅助类。"""

import asyncio
import contextlib
from collections.abc import Generator
from typing import Any

import uvicorn


class _LifespanSafeApp:
    """在 lifespan 阶段抑制 CancelledError traceback 的 ASGI 包装器。

    组合根通过 ``should_exit`` 优雅关闭服务器；若关闭因连接挂起而超时被
    强制取消，孤儿 lifespan 任务会在进程收尾时被 asyncio 取消，此处抑制
    其异常日志。
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
