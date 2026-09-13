"""进程运行编排：激活模块生命周期并让已贡献前台或停止事件拥有进程。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from src.contracts import FrontIO, TerminalDispatcher
from src.runtime.assembly import compose_runtime
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from src.contracts import Model, Settings, Tool
    from src.kernel import ContributionBinding, InstanceBinding
    from src.runtime.core import AuroraRuntime

_logger = get_logger(__name__)


class _RuntimeFrontContext:
    """把冻结 Assembly 与进程运行服务合并为按需能力视图。"""

    def __init__(
        self,
        runtime: AuroraRuntime,
        *,
        readline: Callable[[str], str] | None,
        output: Callable[[str], None],
    ) -> None:
        self.settings = runtime.settings
        self._assembly = runtime.assembly
        self._services: dict[type, object] = {
            TerminalDispatcher: runtime.terminal,
            FrontIO: FrontIO(readline=readline, output=output),
        }

    def get[T](self, capability: type[T]) -> T:
        service = self._services.get(capability)
        if service is not None:
            return cast("T", service)
        return self._assembly.get(capability)

    def get_optional[T](self, capability: type[T]) -> T | None:
        service = self._services.get(capability)
        if service is not None:
            return cast("T | None", service)
        return self._assembly.get_optional(capability)


async def run_runtime(
    settings: Settings,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    headless: bool = False,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
    instances: Iterable[InstanceBinding] = (),
    contributions: Iterable[ContributionBinding] = (),
) -> AuroraRuntime:
    """通过统一模块生命周期组合运行时，并让已贡献前台或停止事件拥有进程。"""
    _logger.info("Aurora runtime 启动 headless={}", headless)
    stop = stop_event or asyncio.Event()
    try:
        runtime, lifecycle = await compose_runtime(
            settings,
            model,
            tools,
            output=output,
            instances=instances,
            contributions=contributions,
        )
        await lifecycle.activate(stop)
        _logger.info("Aurora runtime 装配完成")
    except BaseException as error:
        _logger.error("Aurora runtime 启动失败 error_type={}", type(error).__name__)
        raise
    try:
        context = _RuntimeFrontContext(runtime, readline=readline, output=output)
        fronts = tuple(bind(context) for bind in runtime.front_bindings)
        active = tuple(front for front in fronts if not (headless and front.interactive))
        if active:
            await asyncio.gather(*(front.run(stop) for front in active))
        else:
            await stop.wait()
    finally:
        _logger.info("Aurora runtime 开始关闭")
        await lifecycle.close()
        _logger.info("Aurora runtime 已关闭")
    return runtime
