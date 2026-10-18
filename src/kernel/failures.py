"""保留模组故障的归属、原始异常与资源清理结果。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from src.kernel.declaration import AsyncCleanup


class ModuleLifecycleError(RuntimeError):
    """一个模组在明确阶段失败，原始异常保留为原因。"""

    def __init__(self, module_name: str, phase_name: str, error: BaseException) -> None:
        """错误身份不依赖任务名称或文本解析。"""
        self.module_name = module_name
        self.phase_name = phase_name
        self.error = error
        super().__init__(f"模组 {module_name} 的 {phase_name} 阶段失败：{type(error).__name__}：{error}")
        self.__cause__ = error


@dataclass(frozen=True, slots=True)
class ModuleCleanup:
    """准备阶段返回的清理动作仍属于原模组和阶段。"""

    module_name: str
    phase_name: str
    callback: AsyncCleanup

    async def run(self) -> ModuleLifecycleError | None:
        """资源释放失败时返回完整归属，调用方继续清理其他资源。"""
        return await collect_failure(self.module_name, self.phase_name, self.callback())


async def collect_failure(
    module_name: str, phase_name: str, operation: Awaitable[object]
) -> ModuleLifecycleError | None:
    """收集一次独立释放的结果，不以异常中断其他释放动作。"""
    (result,) = await asyncio.gather(operation, return_exceptions=True)
    return ModuleLifecycleError(module_name, phase_name, result) if isinstance(result, BaseException) else None


def raise_failures(failures: list[Exception]) -> None:
    """单一故障保持身份，多个故障一起报告而不丢失后续错误。"""
    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise ExceptionGroup("模组关闭时发生多个错误", failures)
