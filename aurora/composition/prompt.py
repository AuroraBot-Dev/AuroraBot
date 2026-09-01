"""构造并导出 ``src.prompt`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.configuration.prompts import PROMPTS_CONFIG, PromptConfig
from src.prompt import PromptAssembler, PromptCatalog

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig

_SYSTEM_PREFIX = "system."


class PromptOps:
    """提示词目录的窄 ops 端口适配器。"""

    def __init__(self, system: tuple[str, ...], agent_prompts: Mapping[str, str]) -> None:
        self._system = system
        self._agent_prompts = agent_prompts

    def prompt_catalog(self) -> dict[str, Any]:
        return {
            "system": list(self._system),
            "agent_prompts": dict(self._agent_prompts),
        }

    def prompt_detail(self, prompt_id: str) -> dict[str, Any] | None:
        if prompt_id == "system":
            return {"prompt_id": "system", "fragments": list(self._system)}
        content = self._agent_prompts.get(prompt_id)
        return {"prompt_id": prompt_id, "content": content} if content is not None else None


PROMPT_ASSEMBLER = InstanceKey[PromptAssembler]("prompt.assembler")
PROMPT_OPS = InstanceKey[PromptOps]("prompt.ops")


def _register(context: CompositionContext) -> None:
    prompts = context.config.get(PROMPTS_CONFIG)
    system, agent_prompts = _read_prompts(context.config, prompts)
    catalog = PromptCatalog(system, agent_prompts)
    context.provide(PROMPT_ASSEMBLER, PromptAssembler(catalog))
    context.provide(PROMPT_OPS, PromptOps(system, agent_prompts))


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


MODULE_SPEC = ModuleSpec(key=PROMPT_ASSEMBLER, requires=(), register=_register)
