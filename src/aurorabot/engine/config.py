"""``aurorabot.engine`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """AgentTree 运行上界。"""

    max_depth: int
    max_nodes: int
    max_steps: int
