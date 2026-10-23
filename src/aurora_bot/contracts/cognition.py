"""Bot 的认知入口与结果；执行拓扑属于具体执行器。"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurora_agent import RunResult as CognitionResult
from aurora_bot.contracts.agent import _focus_goals
from aurora_bot.contracts.world import WorldFrontier

__all__ = ["CognitionRequest", "CognitionResult"]


@dataclass(frozen=True, slots=True)
class CognitionRequest:
    message: str
    run_id: str | None = None
    agent: str | None = None
    frontier: WorldFrontier = field(default_factory=WorldFrontier)
    caused_by: str | None = None
    memory_scopes: frozenset[str] | None = None
    focus_goal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "focus_goal_ids", _focus_goals(self.focus_goal_ids))
        if self.memory_scopes is not None:
            object.__setattr__(self, "memory_scopes", frozenset(self.memory_scopes))
        if self.run_id is not None and not self.run_id.strip():
            raise ValueError("认知运行身份不能为空")
        if not self.message.strip():
            raise ValueError("CognitionRequest requires a non-empty message")
        if self.caused_by is not None and not self.caused_by.strip():
            raise ValueError("CognitionRequest caused_by must not be empty")
