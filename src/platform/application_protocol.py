from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path


@runtime_checkable
class ApplicationProtocol(Protocol):
    # 获取应用的manifest文件路径
    def manifest_path(self) -> Path: ...

    # 启动时调用
    async def on_start(self) -> None: ...

    # 停止时调用
    async def on_stop(self) -> None: ...

    # 每tick调用一次
    async def on_tick(self) -> None: ...
