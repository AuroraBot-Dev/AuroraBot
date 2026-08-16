"""平台工厂与组合根之间的生命周期契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from src.contracts.ports import ExternalAmpIngressPort, InteractiveInputPort

if TYPE_CHECKING:
    import asyncio

    from src.contracts.configuration import AuroraConfig
    from src.contracts.tool import EffectToolBinding


class PlatformRuntimePort(ExternalAmpIngressPort, InteractiveInputPort, Protocol):
    """平台创建和输入所需的组合运行时表面。"""

    configuration: AuroraConfig


class PlatformServer(Protocol):
    """由组合根统一启动和停止的长驻服务。"""

    started: bool
    should_exit: bool

    async def serve(self) -> None: ...


class PlatformBackground(Protocol):
    """必须持续运行到 stop，且不得吞掉取消的后台协程。"""

    async def __call__(self, stop: asyncio.Event) -> None: ...


class PlatformCleanup(Protocol):
    """必须在有界时间返回且不得吞掉取消的平台清理回调。"""

    async def __call__(self) -> None: ...


class PlatformFactory(Protocol):
    """平台自描述工厂。"""

    async def __call__(self, config: AuroraConfig, runtime: PlatformRuntimePort) -> "PlatformHandle": ...


@dataclass(frozen=True, slots=True)
class PlatformHandle:
    """平台创建后交给组合根管理的资源和任务。"""

    bindings: tuple[EffectToolBinding, ...] = ()
    cleanup: PlatformCleanup | None = None
    background: PlatformBackground | None = None
    server: PlatformServer | None = None
