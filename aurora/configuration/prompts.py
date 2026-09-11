"""解析并注册 ``config/prompts.toml`` 的提示词目录。"""

from __future__ import annotations

from aurora.config import ConfigSpec, TableArrayShape, boolean_field, text_field
from src.prompt.config import PromptConfig, PromptsConfig

PROMPTS_CONFIG = ConfigSpec[PromptsConfig](
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
        container=PromptsConfig,
    ),
)

CONFIG_SPEC = PROMPTS_CONFIG
