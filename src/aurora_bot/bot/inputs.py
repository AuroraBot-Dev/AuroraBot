"""主体领域操作的结构化输入。"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from aurora_bot.contracts.bot import Checkpoint


class StateInput(BaseModel):
    """分页发现目标或安排，指定身份时展开完整恢复状态。"""

    model_config = ConfigDict(extra="forbid")

    section: Literal["goals", "wakes"] = "goals"
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=10, ge=1, le=50, strict=True)
    expected_version: int | None = Field(default=None, ge=0, strict=True)
    goal_id: str | None = None
    wake_id: str | None = None


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
