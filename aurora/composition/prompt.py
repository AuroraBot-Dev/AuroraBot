"""构造并导出 ``src.prompt`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.prompts import PROMPTS_CONFIG
from src.prompt import PromptAssembler, PromptCatalog

if TYPE_CHECKING:
    from aurora.composer import CompositionContext


PROMPT_ASSEMBLER = InstanceKey[PromptAssembler]("prompt.assembler")


def register(context: CompositionContext) -> None:
    configuration = context.config.get(PROMPTS_CONFIG)
    catalog = PromptCatalog(configuration.system, configuration.profiles)
    context.provide(PROMPT_ASSEMBLER, PromptAssembler(catalog, max_characters=configuration.max_characters))
