"""Bot 的认知入口与结果；执行拓扑属于具体执行器。"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurora_bot.contracts.agent import _focus_goals
from aurora_bot.contracts.world import WorldFrontier


@dataclass(frozen=True, slots=True)
class CognitionRequest:
    """请求 Bot 进行认知，不规定执行器内部的节点或委派结构。"""

    message: str
    run_id: str | None = None
    agent: str | None = None
    frontier: WorldFrontier = field(default_factory=WorldFrontier)
    caused_by: str | None = None
    memory_scopes: frozenset[str] | None = None
    focus_goal_ids: tuple[str, ...] = ()
    node_id: str = "root"

    def __post_init__(self) -> None:
        object.__setattr__(self, "focus_goal_ids", _focus_goals(self.focus_goal_ids))
        if self.memory_scopes is not None:
            object.__setattr__(self, "memory_scopes", frozenset(self.memory_scopes))
        if not self.node_id.strip() or (self.run_id is not None and not self.run_id.strip()):
            raise ValueError("认知运行与入口身份不能为空")
        if not self.message.strip():
            raise ValueError("CognitionRequest requires a non-empty message")
        if self.caused_by is not None and not self.caused_by.strip():
            raise ValueError("CognitionRequest caused_by must not be empty")


@dataclass(frozen=True, slots=True)
class CognitionResult:
    """一次执行的结果，不携带节点图；完成不代表 Bot 的目标已经完成。"""

    run_id: str
    output: str = ""
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("认知运行身份不能为空")
        if self.error is not None and not self.error.strip():
            raise ValueError("失败原因不能为空")

    @property
    def status(self) -> str:
        return "completed" if self.error is None else "failed"
