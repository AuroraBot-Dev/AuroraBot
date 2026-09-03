"""构造并导出 ``src.prompt`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.prompts import PROMPTS_CONFIG, PromptConfig
from src.prompt import PromptAssembler, PromptCatalog

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig

_SYSTEM_PREFIX = "system."

PROMPT_ASSEMBLER = InstanceKey[PromptAssembler]("prompt.assembler")


def construct(context: CompositionContext) -> None:
    prompts = context.config.get(PROMPTS_CONFIG)
    system, agent_prompts = _read_prompts(context.config, prompts)
    catalog = PromptCatalog(system, agent_prompts)
    context.provide(PROMPT_ASSEMBLER, PromptAssembler(catalog))


def _read_prompts(
    config: AuroraConfig,
    prompts: tuple[PromptConfig, ...],
) -> tuple[tuple[str, ...], dict[str, str]]:
    prompts_directory = config.project_root / "config" / "prompts"
    system_fragments: list[str] = []
    agent_prompts: dict[str, str] = {}
    for item in prompts:
        content = _read_fragment(prompts_directory, item.source)
        if item.id.startswith(_SYSTEM_PREFIX):
            system_fragments.append(content)
        else:
            agent_prompts[item.id] = content
    if not system_fragments:
        raise ValueError("提示词配置至少需要一个 system 片段")
    if not agent_prompts:
        raise ValueError("提示词配置至少需要一个 Agent prompt")
    return tuple(system_fragments), agent_prompts


def _read_fragment(prompts_directory: Path, source: str) -> str:
    value = (prompts_directory / source).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"提示词文件不能为空：{source}")
    return value


PACKAGE_SPEC = PackageSpec(
    key=PROMPT_ASSEMBLER,
    provides=(PROMPT_ASSEMBLER,),
    requires=(),
    register=construct,
)
