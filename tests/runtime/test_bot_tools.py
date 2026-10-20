"""验证主体操作的结构化输入、状态反馈与失败边界。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from aurorabot.bot.operations import BOT_STATE_TOOL, GOAL_SET_TOOL, WAKE_CANCEL_TOOL, WAKE_SCHEDULE_TOOL, bot_operations
from aurorabot.bot.store import JournalBotState
from aurorabot.contracts import ToolCall, ToolOutput
from aurorabot.contracts.bot import WakeStatus
from aurorabot.operations.registry import OperationRegistry
from aurorabot.operations.tool import operation_tools
from aurorabot.resources.catalog import ResourceCatalog
from aurorabot.tools import ToolRegistry
from aurorabot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_GOAL_ARGUMENTS = {
    "expected_version": 0,
    "goal_id": "aurora:goal/check",
    "purpose": "核对结果",
    "success_condition": "结果已确认",
    "checkpoint": {"pending_actions": ["先查询 operation-7"], "evidence_refs": ["operation:7"]},
}


def _tools(state: JournalBotState, world: SqlAlchemyWorldJournal) -> ToolRegistry:
    """由实际操作定义生成测试工具目录。"""
    operations = bot_operations(state)
    resources = ResourceCatalog(operation.definition.resource for operation in operations)
    registry = OperationRegistry(state.bot_id, operations, resources, world)
    return ToolRegistry(operation_tools(registry, state.bot_id))


def test_bot_can_choose_plan_cancel_and_retry_through_registered_tools(tmp_path: Path) -> None:
    """同一参数模型生成 schema 并验证真实执行输入。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        tools = _tools(state, world)
        try:
            read = await tools.execute(ToolCall("read", BOT_STATE_TOOL))
            assert isinstance(read, ToolOutput)
            assert json.loads(read.content)["version"] == 0
            goal = await tools.execute(ToolCall("goal", GOAL_SET_TOOL, _GOAL_ARGUMENTS))
            assert isinstance(goal, ToolOutput) and not goal.is_error
            assert "先查询 operation-7" in goal.content
            schedule = await tools.execute(
                ToolCall(
                    "schedule",
                    WAKE_SCHEDULE_TOOL,
                    {
                        "expected_version": 1,
                        "wake_id": "aurora:wake/check",
                        "due_at": "2026-10-18T12:00:00+00:00",
                        "message": "核对先前操作",
                        "goal_id": "aurora:goal/check",
                    },
                )
            )
            assert isinstance(schedule, ToolOutput) and not schedule.is_error
            cancel = ToolCall("cancel", WAKE_CANCEL_TOOL, {"expected_version": 2, "wake_id": "aurora:wake/check"})
            result = await tools.execute(cancel)
            retry = await tools.execute(cancel)
            assert result == retry
            assert (await state.snapshot()).wake("aurora:wake/check").status is WakeStatus.CANCELLED
            definition = next(item for item in tools.definitions if item.name == GOAL_SET_TOOL)
            assert "expected_version" in definition.parameters["required"]
            assert tools.scopes_for(cancel).publish == frozenset({state.scope})
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [{"expected_version": True}, {"unknown": "value"}, {"goal_id": "wrong"}])
def test_invalid_tool_input_cannot_change_subject(tmp_path: Path, invalid: dict[str, object]) -> None:
    """布尔版本、额外字段与错误身份都不能写入主体。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        state = JournalBotState(world, "aurora:bot/test")
        tools = _tools(state, world)
        try:
            result = await tools.execute(ToolCall("invalid", GOAL_SET_TOOL, {**_GOAL_ARGUMENTS, **invalid}))
            assert isinstance(result, ToolOutput) and result.is_error
            assert (await state.snapshot()).goals == ()
        finally:
            await world.close()

    asyncio.run(scenario())
