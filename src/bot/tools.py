"""让 Bot 读取、修订目标并安排未来活动的声明式工具。"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.bot.codec import snapshot_data
from src.contracts import ToolCall, ToolDefinition, ToolOutput, ToolScopes
from src.contracts.bot import BotChange, Checkpoint, Goal, GoalStatus, WakePlan, WakeStatus

if TYPE_CHECKING:
    from src.contracts import Tool
    from src.contracts.pkgs.bot import BotStateStore

BOT_STATE_TOOL = "aurora:tool/bot_state"
GOAL_SET_TOOL = "aurora:tool/goal_set"
WAKE_SCHEDULE_TOOL = "aurora:tool/wake_schedule"
WAKE_CANCEL_TOOL = "aurora:tool/wake_cancel"


class CheckpointInput(BaseModel):
    """Bot 提供的工作恢复依据。"""

    model_config = ConfigDict(extra="forbid")

    stage: str = ""
    confirmed: tuple[str, ...] = ()
    pending_actions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def checkpoint(self) -> Checkpoint:
        """构造领域检查点，保留每个字段的独立语义。"""
        return Checkpoint(
            stage=self.stage,
            confirmed=self.confirmed,
            pending_actions=self.pending_actions,
            constraints=self.constraints,
            open_questions=self.open_questions,
            evidence_refs=self.evidence_refs,
        )


class GoalInput(BaseModel):
    """完整替换一项目标与检查点，需要显式读取版本。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0, strict=True)
    goal_id: str
    purpose: str
    success_condition: str
    status: Literal["active", "paused", "completed", "abandoned"] = "active"
    checkpoint: CheckpointInput = Field(default_factory=CheckpointInput)


class ScheduleInput(BaseModel):
    """在绝对时间唤醒一次；重启后仍保留安排。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0, strict=True)
    wake_id: str
    due_at: AwareDatetime
    message: str
    goal_id: str | None = None


class CancelInput(BaseModel):
    """取消一项尚未开始的安排。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0, strict=True)
    wake_id: str


class BotStateTool:
    """读取 Bot 当前版本、目标、恢复检查点与安排。"""

    def __init__(self, state: BotStateStore) -> None:
        """注入所属主体的读取与提交端口。"""
        self._state = state
        self._definition = ToolDefinition(
            BOT_STATE_TOOL,
            "读取自己的持久目标、恢复检查点与未来活动安排；修改前读取 version。",
            {"type": "object", "properties": {}, "additionalProperties": False},
        )

    @property
    def definition(self) -> ToolDefinition:
        """返回可发现的操作定义。"""
        return self._definition

    def resolve_scopes(self, _call: ToolCall) -> ToolScopes:
        """披露主体状态的新变化。"""
        return ToolScopes(observe=frozenset({self._state.scope}))

    async def execute(self, call: ToolCall) -> ToolOutput:
        """读取并序列化实际持久状态。"""
        if call.arguments:
            raise ValueError("主体状态读取不接受参数")
        snapshot = await self._state.snapshot()
        return ToolOutput(json.dumps(snapshot_data(snapshot), ensure_ascii=False, separators=(",", ":")))


class BotChangeTool:
    """由统一定义校验并提交一类主体操作。"""

    def __init__(self, state: BotStateStore, name: str, description: str, model: type[BaseModel]) -> None:
        """从参数模型生成工具描述，避免维护重复格式。"""
        self._state = state
        self._model = model
        self._definition = ToolDefinition(name, description, model.model_json_schema())

    @property
    def definition(self) -> ToolDefinition:
        """返回参数校验与模型发现共用的定义。"""
        return self._definition

    def resolve_scopes(self, _call: ToolCall) -> ToolScopes:
        """读取前披露变化，结果提交到所属主体的世界域。"""
        return ToolScopes(observe=frozenset({self._state.scope}), publish=frozenset({self._state.scope}))

    async def execute(self, call: ToolCall) -> ToolOutput:
        """验证结构化参数后提交一个带幂等身份的原子修改。"""
        parameters = self._model.model_validate(dict(call.arguments))
        change = await self._change(call, parameters)
        snapshot = await self._state.apply(change)
        return ToolOutput(json.dumps(snapshot_data(snapshot), ensure_ascii=False, separators=(",", ":")))

    async def _change(self, call: ToolCall, parameters: BaseModel) -> BotChange:
        """把操作输入转换成主体契约，不产生外部行动。"""
        if isinstance(parameters, GoalInput):
            goal = Goal(
                parameters.goal_id,
                parameters.purpose,
                parameters.success_condition,
                GoalStatus(parameters.status),
                parameters.checkpoint.checkpoint(),
            )
            return BotChange(self._command_id(call, parameters.expected_version), parameters.expected_version, (goal,))
        if isinstance(parameters, ScheduleInput):
            wake = WakePlan(parameters.wake_id, parameters.due_at, parameters.message, parameters.goal_id)
            return BotChange(
                self._command_id(call, parameters.expected_version), parameters.expected_version, wakes=(wake,)
            )
        if isinstance(parameters, CancelInput):
            snapshot = await self._state.snapshot()
            wake = replace(snapshot.wake(parameters.wake_id), status=WakeStatus.CANCELLED, detail="Bot 取消了安排")
            return BotChange(
                self._command_id(call, parameters.expected_version), parameters.expected_version, wakes=(wake,)
            )
        raise TypeError("未知主体操作参数")

    @staticmethod
    def _command_id(call: ToolCall, version: int) -> str:
        """将调用身份限定在操作与读取版本内。"""
        return f"tool:{call.name}:{version}:{call.call_id}"


def bot_tools(state: BotStateStore) -> tuple[Tool, ...]:
    """提供最小完整的主体读取、选择与安排能力。"""
    return (
        BotStateTool(state),
        BotChangeTool(
            state,
            GOAL_SET_TOOL,
            "建立或完整修订自己的目标和恢复检查点，可主动暂缓、完成或放弃；填写明确的完成条件。",
            GoalInput,
        ),
        BotChangeTool(
            state,
            WAKE_SCHEDULE_TOOL,
            "登记一次持久的未来检查，时间必须包含时区；可关联活跃目标。登记成功后可以结束当前思考。",
            ScheduleInput,
        ),
        BotChangeTool(state, WAKE_CANCEL_TOOL, "取消自己尚未开始的未来活动安排。", CancelInput),
    )
