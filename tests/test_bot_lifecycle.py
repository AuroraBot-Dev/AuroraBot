"""以真实装配验证 Bot 自定目标、结束认知和重启恢复。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from test_assembly import FakeModel

from aurora import load_config
from aurorabot.contracts import ChatMessage, ModelRequest, ToolCall, TreeStatus
from aurorabot.contracts.bot import BotChange, Checkpoint, Goal, WakeStatus
from aurorabot.contracts.pkgs.bot import BotClock, BotStateStore
from aurorabot.runtime import assemble_runtime

if TYPE_CHECKING:
    from pathlib import Path

_SCHEDULE_STEP = 2


class PlanningModel(FakeModel):
    """依次选择目标、安排未来检查并结束本次认知。"""

    async def complete(self, request: ModelRequest) -> ChatMessage:
        """用确定的结构化调用模拟主体选择。"""
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatMessage.assistant(
                tool_calls=(
                    ToolCall(
                        "goal",
                        "aurora:tool/definition/goal_set",
                        {
                            "expected_version": 0,
                            "goal_id": "aurora:goal/experiment",
                            "purpose": "等待实验并比较结果",
                            "success_condition": "比较结果已经保存",
                            "checkpoint": {
                                "stage": "等待实验完成",
                                "pending_actions": ["operation-7 已经发起，先查询完成状态"],
                                "evidence_refs": ["experiment:started:7"],
                            },
                        },
                    ),
                )
            )
        if len(self.requests) == _SCHEDULE_STEP:
            return ChatMessage.assistant(
                tool_calls=(
                    ToolCall(
                        "wake",
                        "aurora:tool/definition/wake_schedule",
                        {
                            "expected_version": 1,
                            "wake_id": "aurora:wake/experiment",
                            "due_at": "2026-10-18T12:00:00+00:00",
                            "message": "比较实验结果",
                            "goal_id": "aurora:goal/experiment",
                        },
                    ),
                )
            )
        return ChatMessage.assistant("我会在约定时间检查实验。")


def test_bot_resumes_its_own_goal_after_restart_without_new_user_input(configured_project: Path) -> None:
    """工具选择经过引擎落库，新的进程在到期时获得检查点并继续。"""

    async def scenario() -> None:
        config = load_config(configured_project)
        runtime = assemble_runtime(config, PlanningModel(), output=lambda _: None)
        try:
            result = await runtime.run("按你自己的判断安排检查。")
            assert result.status is TreeStatus.COMPLETED
            state = await runtime.assembly.get(BotStateStore).snapshot()
            assert state.wake("aurora:wake/experiment").status is WakeStatus.PENDING
        finally:
            await runtime.world.close()
        model = FakeModel()
        reopened = assemble_runtime(config, model, output=lambda _: None)
        try:
            clock = reopened.assembly.get(BotClock)
            await clock.evaluate_once(datetime(2026, 10, 18, 12, tzinfo=UTC))
            assert len(model.requests) == 1
            system = model.requests[0].messages[0].content
            assert "operation-7 已经发起，先查询完成状态" in system
            assert "experiment:started:7" in system
            assert "比较实验结果" in model.requests[0].messages[1].content
            state = await reopened.assembly.get(BotStateStore).snapshot()
            assert state.wake("aurora:wake/experiment").status is WakeStatus.COMPLETED
        finally:
            await reopened.world.close()

    asyncio.run(scenario())


def test_required_context_overflow_stops_before_model_or_action(configured_project: Path) -> None:
    """必要恢复状态超限时留下明确失败记录，不发送缺失约束的请求。"""

    async def scenario() -> None:
        model = FakeModel()
        runtime = assemble_runtime(load_config(configured_project), model, output=lambda _: None)
        try:
            goal = Goal(
                "aurora:goal/large",
                "核对复杂结果",
                "所有约束得到满足",
                checkpoint=Checkpoint(constraints=("必须保留的约束" * 6000,)),
            )
            await runtime.assembly.get(BotStateStore).apply(BotChange("large", 0, (goal,)))
            result = await runtime.run("继续核对。")
            assert result.status is TreeStatus.FAILED
            assert model.requests == []
            failure = await runtime.world.commit(f"{result.tree_id}:tree:failed")
            assert failure is not None and "必要上下文超过容量" in failure.summary
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
