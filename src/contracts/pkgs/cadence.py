"""``cadence`` 暴露的全局端口：世界驱动主动节律契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio

    from src.contracts.pkgs.runtime import TreeLauncher
    from src.contracts.resource import ResourceRef
    from src.contracts.rhythm import RhythmObservation, RhythmPrediction


class RhythmPolicy(Protocol):
    """轻量节律判断，与计时服务和认知运行器分别装配。"""

    @property
    def ref(self) -> ResourceRef:
        """返回当前策略或权重的确定资源版本。"""
        ...

    def evaluate(self, observation: RhythmObservation, hidden: tuple[float, ...] = ()) -> RhythmPrediction:
        """由显式输入和隐状态产生下一次推理机会。"""
        ...


class Cadence(Protocol):
    """世界提交驱动的主动节律。"""

    agent: str | None

    @property
    def enabled(self) -> bool: ...

    def status(self) -> dict[str, object]: ...

    async def initialize(self) -> None: ...

    async def evaluate_once(self) -> None: ...

    async def run(self, stop_event: asyncio.Event) -> None: ...

    def bind_launcher(self, launcher: TreeLauncher) -> None: ...
