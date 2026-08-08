"""提示词片段与同构 Agent 循环中每轮消息的装配。"""

from __future__ import annotations

from src.prompt.composer import PromptComposer, external_data
from src.prompt.models import PromptCatalog, PromptDocument, PromptSection

__all__ = [
    "PromptCatalog",
    "PromptComposer",
    "PromptDocument",
    "PromptSection",
    "external_data",
]
