"""回收等待保护调用者取消，但不能把操作本身的失败当作等待中断。"""

from __future__ import annotations

import asyncio

import pytest

from aurorabot.utils.tasks import wait_for_completion


@pytest.mark.parametrize("cancelled", [False, True])
def test_completion_propagates_the_operation_failure(cancelled: bool) -> None:
    """操作自身失败或取消时，应直接结束等待并保留原始异常。"""
    original = asyncio.CancelledError("操作自行取消") if cancelled else ValueError("操作失败")

    async def operation() -> None:
        """操作异常与等待者取消有不同来源。"""
        raise original

    async def scenario() -> None:
        """操作已经完成后再读取结果，覆盖取消任务不会被无限重试。"""
        task = asyncio.create_task(operation())
        await asyncio.wait((task,))
        with pytest.raises(type(original)) as captured:
            await wait_for_completion(task)
        if not cancelled:
            assert captured.value is original
        assert task.cancelled() is cancelled

    asyncio.run(scenario())
