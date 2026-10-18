"""``src.cadence`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    """世界提交驱动的节律策略。"""

    enabled: bool
    agent: str
    poll_seconds: float


@dataclass(frozen=True, slots=True)
class ReactionConfig:
    """把一类已提交的外部事件路由到一个即时会话 Agent 的策略。"""

    source: str
    event_kind: str
    agent: str
    contains_any: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReactionsConfig:
    """``reactions.toml`` 声明的全部即时路由规则。"""

    reactions: tuple[ReactionConfig, ...]
