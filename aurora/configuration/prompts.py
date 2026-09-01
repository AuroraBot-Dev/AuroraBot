"""解析并注册 ``config/prompts.toml`` 的提示词目录。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import (
    ConfigSpec,
    TableArrayShape,
    boolean_field,
    text_field,
)


@dataclass(frozen=True, slots=True)
class PromptConfig:
    id: str
    source: str
    enabled: bool = True


PROMPTS_CONFIG = ConfigSpec[tuple[PromptConfig, ...]](
    name="prompts",
    path="config/prompts.toml",
    shape=TableArrayShape(
        path=("prompt",),
        fields=(
            text_field("id"),
            text_field("source"),
            boolean_field("enabled"),
        ),
        model=PromptConfig,
    ),
)
