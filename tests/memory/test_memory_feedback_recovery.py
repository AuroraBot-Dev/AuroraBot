"""反馈已持久化而操作回执中断时，重启重试不会重复记录判断。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurorabot.contracts.operation import OperationRequest, OperationResult, OperationStatus
from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.runtime import assemble_runtime
from tests.memory.operations_support import feedback_arguments, prepared_runtime, request
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path


def test_committed_feedback_survives_receipt_interruption_and_restart(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """在领域效果和外层回执之间中断，恢复时沿用原判断身份。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, model_id):
            registry = runtime.assembly.get(OperationRegistry)
            call = request(runtime, "interrupted", "command/feedback", feedback_arguments(model_id))

            async def interrupt_receipt(_request: OperationRequest, _result: OperationResult) -> OperationResult:
                """反馈提交之后模拟进程退出，保留缺失外层回执的真实状态。"""
                raise asyncio.CancelledError

            monkeypatch.setattr(registry, "_record_result", interrupt_receipt)
            with pytest.raises(asyncio.CancelledError):
                await registry.dispatch(call)
            assert await runtime.world.commit(f"{call.identity}:feedback") is not None
            assert await runtime.world.commit(f"{call.identity}:result") is None
        reopened = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)
        try:
            restored = reopened.assembly.get(OperationRegistry)
            result = await restored.dispatch(call)
            assert result.status is OperationStatus.SUCCEEDED
            assert result.data["feedback_id"] == f"{call.identity}:feedback"
            scope = f"{reopened.assembly.get(BotStateStore).scope}/memory"
            records = await reopened.world.commits(scope, 0, 10)
            assert len(records) == 1
        finally:
            await reopened.world.close()

    asyncio.run(scenario())
