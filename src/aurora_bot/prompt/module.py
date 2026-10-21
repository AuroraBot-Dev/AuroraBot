"""``aurora_bot.prompt`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts.pkgs.prompt import PromptAssembler as PromptAssemblerPort
from aurora_bot.contracts.prompt import PROMPT_MEDIA_TYPE, PromptFragment
from aurora_bot.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceKey
from aurora_bot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.prompt.composer import PromptAssembler
from aurora_bot.prompt.config import PromptsConfig
from aurora_bot.prompt.models import PromptCatalog

if TYPE_CHECKING:
    from pathlib import Path


@module(
    name="prompt",
    provides=PromptAssemblerPort,
    requires=PromptAssemblerPort,
    contributes=(RESOURCE_CONTRIBUTIONS, RESOURCE_CONTENTS),
)
def build(context: ModuleContext) -> PromptAssemblerPort:
    """资源描述来自实际载入的片段，不从配置路径推断内容版本。"""
    assembler = context.get_optional(PromptAssemblerPort)
    if assembler is None:
        config = context.settings.resolve(PromptsConfig)
        directory = context.settings.project_root / "config" / "prompts"
        fragments = tuple(
            PromptFragment(ResourceKey.parse(item.id), _read_fragment(directory, item.source))
            for item in config.prompts
            if item.enabled
        )
        assembler = PromptAssembler(PromptCatalog(fragments))
    for fragment in assembler.catalog.fragments:
        context.contribute(RESOURCE_CONTRIBUTIONS, fragment.resource)
        context.contribute(
            RESOURCE_CONTENTS, ResourceContent(fragment.ref, fragment.content.encode("utf-8"), PROMPT_MEDIA_TYPE)
        )
    return assembler


def _read_fragment(directory: Path, source: str) -> str:
    value = (directory / source).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"提示词文件不能为空：{source}")
    return value


MODULE = build
