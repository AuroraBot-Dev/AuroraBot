"""异步回收期间隔离调用者取消，并保留取消结果。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Never


async def wait_for_completion[T](future: asyncio.Future[T]) -> tuple[T, asyncio.CancelledError | None]:
    """等待已有任务完成，调用者的取消由宿主在回收完成后处理。"""
    interrupted: asyncio.CancelledError | None = None
    while True:
        try:
            return await asyncio.shield(future), interrupted
        except asyncio.CancelledError as error:
            if future.cancelled():
                raise
            if interrupted is None:
                interrupted = error


def raise_with_cleanup(
    error: BaseException, failures: Iterable[BaseException], interrupted: asyncio.CancelledError | None = None
) -> Never:
    """清理错误不能覆盖原始错误，取消保持取消语义并携带全部失败原因。"""
    additional = [failure for failure in failures if failure is not error]
    if interrupted is not None and not isinstance(error, asyncio.CancelledError):
        raise interrupted from BaseExceptionGroup("运行失败后的资源释放被取消", [error, *additional])
    if not additional:
        raise error
    if isinstance(error, Exception):
        raise BaseExceptionGroup("运行与资源清理同时失败", [error, *additional]) from None
    raise error from BaseExceptionGroup("资源清理失败", additional)
