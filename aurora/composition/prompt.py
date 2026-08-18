"""构造并导出 ``src.prompt`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.prompt import PROMPT_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG
from src.prompt import PromptAssembler, PromptCatalog

if TYPE_CHECKING:
    from aurora.composer import CompositionContext


PROMPT_ASSEMBLER = InstanceKey[PromptAssembler]("prompt.assembler")


def register(context: CompositionContext) -> None:
    configuration = context.config.get(PROMPT_CONFIG)
    runtime = context.config.get(RUNTIME_CONFIG)
    if runtime.profile not in configuration.profiles:
        raise ValueError(f"root profile 没有对应提示词：{runtime.profile}")
    catalog = PromptCatalog(configuration.system, configuration.profiles)
    context.provide(PROMPT_ASSEMBLER, PromptAssembler(catalog, max_characters=configuration.max_characters))
