"""不接管进程 signal 的 Panel Uvicorn 生命周期包装。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING

import uvicorn

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

    from ops.panel.contracts import PanelSettings


class _SignalFreeServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


class PanelServer:
    def __init__(self, app: FastAPI, settings: PanelSettings) -> None:
        config = uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            access_log=False,
            log_config=None,
            lifespan="on",
        )
        self._server = _SignalFreeServer(config)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            if not self._task.done():
                return
            completed, self._task = self._task, None
            await completed
        task = asyncio.create_task(_serve_without_exit(self._server), name="aurora-panel-server")
        self._task = task
        try:
            while not self._server.started:
                if task.done():
                    await task
                    raise RuntimeError("Panel 服务启动前已停止")
                await asyncio.sleep(0.01)
        except BaseException:
            self._server.should_exit = True
            if not task.done():
                await task
            self._task = None
            raise

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        self._server.should_exit = True
        await task

    @property
    def started(self) -> bool:
        return self._server.started and self._task is not None and not self._task.done()


async def _serve_without_exit(server: uvicorn.Server) -> None:
    try:
        await server.serve()
    except SystemExit as error:
        raise RuntimeError("Panel 服务启动失败") from error
