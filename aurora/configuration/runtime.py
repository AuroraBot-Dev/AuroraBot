"""解析 ``config/runtime.toml`` 的进程级运行时配置。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import (
    ConfigSpec,
    TableShape,
    text_field,
)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """进程级 root Agent 入口与统一日志级别。"""

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


RUNTIME_CONFIG = ConfigSpec[RuntimeConfig](
    name="runtime",
    path="config/runtime.toml",
    shape=TableShape(
        path=("runtime",),
        fields=(
            text_field("profile"),
            text_field("node_id"),
            text_field("agent"),
            text_field("log_level"),
        ),
        model=RuntimeConfig,
    ),
)
