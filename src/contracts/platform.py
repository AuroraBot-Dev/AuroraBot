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
    """EventSource 面：持续运行到 stop，把环境事实归一化为 AMP。"""

    async def __call__(self, stop: asyncio.Event) -> None: ...


class PlatformCleanup(Protocol):
    """必须在有界时间返回且不得吞掉取消的平台清理回调。"""

    async def __call__(self) -> None: ...


class PlatformFactory(Protocol):
    """平台自描述工厂。"""

    async def __call__(self, config: AuroraConfig, runtime: PlatformRuntimePort) -> "PlatformHandle": ...


@dataclass(frozen=True, slots=True)
class PlatformHandle:
    """平台创建后交给组合根管理的贡献与生命周期。

    ``effect_tools`` 是 EffectTool 绑定；``event_sources`` 是 EventSource 面；
    ``server`` 与 ``cleanup`` 是 Lifecycle 管理的长驻服务与清理回调。
    """

    effect_tools: tuple[EffectToolBinding, ...] = ()
    event_sources: tuple[PlatformBackground, ...] = ()
    cleanup: PlatformCleanup | None = None
    server: PlatformServer | None = None
