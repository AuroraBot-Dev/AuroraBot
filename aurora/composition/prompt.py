"""Prompt 配置到 PromptAssembler 的构造阶段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.prompt import PromptAssembler, PromptCatalog

if TYPE_CHECKING:
    from aurora.configuration import AuroraConfiguration


def assemble_prompt(configuration: AuroraConfiguration) -> PromptAssembler:
    catalog = PromptCatalog(configuration.prompt.system, configuration.prompt.profiles)
    return PromptAssembler(catalog, max_characters=configuration.runner.max_prompt_characters)
