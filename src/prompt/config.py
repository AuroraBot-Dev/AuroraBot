"""``src.prompt`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptConfig:
    """一条提示词条目。"""

    id: str
    source: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class PromptsConfig:
    """``prompts.toml`` 的全部提示词条目。"""

    prompts: tuple[PromptConfig, ...]
