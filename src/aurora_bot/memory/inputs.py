"""Bot 查询实际曝光和评估记忆的结构化参数。"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class RecallInput(BaseModel):
    """按问题和目标补取记忆摘要，原始证据另行展开。"""

    model_config = ConfigDict(extra="forbid")

    query: str = ""
    focus_goal_ids: tuple[str, ...] = ()
    scopes: tuple[str, ...] | None = None
    cursor: int | None = Field(default=None, ge=0, strict=True)
    observed_at: AwareDatetime | None = None
    max_characters: int = Field(default=4000, ge=1, le=16000, strict=True)


class SourceInput(BaseModel):
    """在明确历史边界内展开一项世界证据。"""

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(min_length=1)
    cursor: int | None = Field(default=None, ge=0, strict=True)
    observed_at: AwareDatetime | None = None


class TrainingInput(BaseModel):
    """以真实模型请求为身份导出当时的评分输入。"""

    model_config = ConfigDict(extra="forbid")

    model_request_id: str = Field(min_length=1)


class ExposuresInput(BaseModel):
    """按固定世界上界扫描一页；未指定起点时读取最近一页。"""

    model_config = ConfigDict(extra="forbid")

    after: int | None = Field(default=None, ge=0, strict=True)
    until_cursor: int | None = Field(default=None, ge=0, strict=True)
    limit: int = Field(default=100, ge=1, le=256, strict=True)
    run_id: str | None = None


class FeedbackInput(BaseModel):
    """对一次具体上下文中的记忆作显式判断，并引用后续获知的证据。"""

    model_config = ConfigDict(extra="forbid")

    model_request_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    helpful: bool = Field(strict=True)
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)
    supersedes: str | None = None
