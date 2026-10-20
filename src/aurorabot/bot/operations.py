"""主体选择通过统一领域操作暴露给环境。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from aurorabot.bot.inputs import CancelInput, GoalInput, ScheduleInput, StateInput
from aurorabot.bot.views import change_view, state_view
from aurorabot.contracts import ToolScopes
from aurorabot.contracts.bot import BotChange, Goal, GoalStatus, WakePlan, WakeStatus
from aurorabot.contracts.operation import (
    OperationDefinition,
    OperationKind,
    OperationRequest,
    OperationResult,
    OperationStatus,
)
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.utils.serialization import thaw_json

if TYPE_CHECKING:
    from pydantic import BaseModel

    from aurorabot.contracts.operation import Operation
    from aurorabot.contracts.pkgs.bot import BotStateStore

BOT_STATE_TOOL = "aurora:tool/definition/bot_state"
GOAL_SET_TOOL = "aurora:tool/definition/goal_set"
WAKE_SCHEDULE_TOOL = "aurora:tool/definition/wake_schedule"
WAKE_CANCEL_TOOL = "aurora:tool/definition/wake_cancel"


class BotOperation:
    """由同一输入结构驱动主体状态的查询与修改。"""

    def __init__(self, state: BotStateStore, definition: OperationDefinition, parameters: type[BaseModel]) -> None:
        """注入所属主体和参数模型，不依赖工具或终端实现。"""
        self._state = state
        self._definition = definition
        self._parameters = parameters

    @property
    def definition(self) -> OperationDefinition:
        """提供统一的资源、调用和发现定义。"""
        return self._definition

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """查询只观察，命令同时发布所属主体状态。"""
        publish = frozenset({self._state.scope}) if request.kind is OperationKind.COMMAND else frozenset()
        return ToolScopes(observe=frozenset({self._state.scope}), publish=publish)

    async def execute(self, request: OperationRequest) -> OperationResult:
        """执行领域校验，显式报告没有产生业务效果的拒绝。"""
        try:
            parameters = self._parameters.model_validate(thaw_json(request.arguments))
            if isinstance(parameters, StateInput):
                snapshot = await self._state.snapshot()
                data = state_view(snapshot, parameters)
            else:
                change = await self._change(request, parameters)
                snapshot = await self._state.apply(change)
                data = change_view(snapshot, change)
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))
        return OperationResult(data)

    async def _change(self, request: OperationRequest, parameters: BaseModel) -> BotChange:
        """将已校验输入转换成原子状态选择。"""
        command_id = request.identity
        if isinstance(parameters, GoalInput):
            goal = Goal(
                parameters.goal_id,
                parameters.purpose,
                parameters.success_condition,
                GoalStatus(parameters.status),
                parameters.checkpoint.checkpoint(),
            )
            return BotChange(command_id, parameters.expected_version, (goal,))
        if isinstance(parameters, ScheduleInput):
            wake = WakePlan(parameters.wake_id, parameters.due_at, parameters.message, parameters.goal_id)
            return BotChange(command_id, parameters.expected_version, wakes=(wake,))
        if isinstance(parameters, CancelInput):
            snapshot = await self._state.snapshot()
            wake = replace(snapshot.wake(parameters.wake_id), status=WakeStatus.CANCELLED, detail="Bot 取消了安排")
            return BotChange(command_id, parameters.expected_version, wakes=(wake,))
        raise TypeError("未知主体操作参数")


def bot_operation_specs() -> tuple[tuple[OperationDefinition, type[BaseModel]], ...]:
    """声明主体读取、目标选择和未来安排的输入，不构造状态服务。"""
    definitions = (
        (
            "aurora:bot/query/state",
            BOT_STATE_TOOL,
            "分页发现自己的目标或安排；指定 goal_id 或 wake_id 展开完整恢复状态。后续页用 expected_version 固定版本。",
            StateInput,
        ),
        (
            "aurora:bot/command/goal_set",
            GOAL_SET_TOOL,
            "建立或完整修订自己的目标和恢复检查点，可主动暂缓、完成或放弃；填写明确的完成条件。",
            GoalInput,
        ),
        (
            "aurora:bot/command/wake_schedule",
            WAKE_SCHEDULE_TOOL,
            "登记一次持久的未来检查，时间必须包含时区；可关联活跃目标。登记成功后可以结束当前思考。",
            ScheduleInput,
        ),
        (
            "aurora:bot/command/wake_cancel",
            WAKE_CANCEL_TOOL,
            "取消自己尚未开始的未来活动安排。",
            CancelInput,
        ),
    )
    return tuple(
        (
            OperationDefinition(ResourceRef(ResourceKey.parse(key), "2"), text, model.model_json_schema(), tool, True),
            model,
        )
        for key, tool, text, model in definitions
    )


def bot_operations(state: BotStateStore) -> tuple[Operation, ...]:
    """把同一份定义与输入绑定到当前主体状态。"""
    return tuple(BotOperation(state, definition, parameters) for definition, parameters in bot_operation_specs())
