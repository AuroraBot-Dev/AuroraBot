"""``src.prompt`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.prompt import PromptAssembler as PromptAssemblerPort
from src.contracts.prompt import PROMPT_MEDIA_TYPE, PromptFragment
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceKey
from src.kernel import ModuleContext, module
from src.prompt import PromptAssembler, PromptCatalog
from src.prompt.config import PromptConfig, PromptsConfig

if TYPE_CHECKING:
    from pathlib import Path


async def ready(context: ModuleContext) -> None:
    """启动认知前保存实际片段，文件变化与重启不影响已记录版本的读取。"""
    store = context.get(ArtifactStore)
    for fragment in context.get(PromptAssemblerPort).catalog.fragments:
        info = await store.put(fragment.key, fragment.content.encode("utf-8"), media_type=PROMPT_MEDIA_TYPE)
        if info.ref != fragment.ref:
            raise ValueError(f"提示词正文存储返回了不一致的版本：{fragment.key}")


@module(
    name="prompt",
    provides=PromptAssemblerPort,
    requires=(PromptAssemblerPort, ArtifactStore),
    contributes=RESOURCE_CONTRIBUTIONS,
    ready=ready,
)
def build(context: ModuleContext) -> PromptAssemblerPort:
    """资源描述来自实际载入的片段，不从配置路径推断内容版本。"""
    assembler = context.get_optional(PromptAssemblerPort)
    if assembler is None:
        config = context.settings.resolve(PromptsConfig)
        directory = context.settings.project_root / "config" / "prompts"
        assembler = PromptAssembler(PromptCatalog(_read_prompts(directory, config.prompts)))
    for fragment in assembler.catalog.fragments:
        context.contribute(RESOURCE_CONTRIBUTIONS, fragment.resource)
    return assembler


def _read_prompts(
    directory: Path,
    prompts: tuple[PromptConfig, ...],
) -> tuple[PromptFragment, ...]:
    """保留配置声明的资源身份与系统片段顺序。"""
    return tuple(
        PromptFragment(ResourceKey.parse(item.id), _read_fragment(directory, item.source))
        for item in prompts
        if item.enabled
    )


def _read_fragment(directory: Path, source: str) -> str:
    value = (directory / source).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"提示词文件不能为空：{source}")
    return value


MODULE = build
