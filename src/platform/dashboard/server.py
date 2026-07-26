"""Dashboard uvicorn 服务器辅助类。"""

import contextlib
from collections.abc import Generator
from typing import Any

import uvicorn


class SignalSafeServer(uvicorn.Server):
    """禁止 uvicorn 自行捕获进程信号，由组合根统一管理停止流程。"""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, Any, None]:  # type: ignore[no-untyped-def]
        yield
