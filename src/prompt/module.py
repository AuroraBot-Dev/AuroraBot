"""``src.prompt`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.pkgs.prompt import PromptAssembler as PromptAssemblerPort
from src.kernel import ModuleContext, module
from src.prompt import PromptAssembler, PromptCatalog
from src.prompt.config import PromptConfig, PromptsConfig

if TYPE_CHECKING:
    from pathlib import Path

_SYSTEM_PREFIX = "system."


@module(name="prompt", provides=PromptAssemblerPort)
def build(context: ModuleContext) -> PromptAssemblerPort:
    config = context.settings.resolve(PromptsConfig)
    directory = context.settings.project_root / "config" / "prompts"
    system, agent_prompts = _read_prompts(directory, config.prompts)
    return PromptAssembler(PromptCatalog(system, agent_prompts))


def _read_prompts(
    directory: Path,
    prompts: tuple[PromptConfig, ...],
) -> tuple[tuple[str, ...], dict[str, str]]:
    system_fragments: list[str] = []
    agent_prompts: dict[str, str] = {}
    for item in prompts:
        content = _read_fragment(directory, item.source)
        if item.id.startswith(_SYSTEM_PREFIX):
            system_fragments.append(content)
        else:
            agent_prompts[item.id] = content
    if not system_fragments:
        raise ValueError("提示词配置至少需要一个 system 片段")
    if not agent_prompts:
        raise ValueError("提示词配置至少需要一个 Agent prompt")
    return tuple(system_fragments), agent_prompts


def _read_fragment(directory: Path, source: str) -> str:
    value = (directory / source).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"提示词文件不能为空：{source}")
    return value


MODULE = build
