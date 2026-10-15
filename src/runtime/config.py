"""``src.runtime`` 的进程级配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """进程级 root Agent 入口与日志级别。"""

    profile: str
    node_id: str
    agent: str
    log_level: str

    def __post_init__(self) -> None:
        if not self.profile.strip():
            raise ValueError("profile 不能为空")
        if not self.node_id.strip():
            raise ValueError("node_id 不能为空")
        if not self.agent.strip():
            raise ValueError("agent 不能为空")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "NONE"}:
            raise ValueError("log_level 必须是日志级别或 NONE")
