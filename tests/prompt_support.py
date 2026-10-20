"""为只关注上下文文本的测试创建具有明确身份的提示词片段。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurorabot.contracts.prompt import PromptFragment
from aurorabot.contracts.resource import ResourceKey
from aurorabot.prompt import PromptCatalog

if TYPE_CHECKING:
    from collections.abc import Mapping


def make_prompt_catalog(system: tuple[str, ...], agents: Mapping[str, str]) -> PromptCatalog:
    """固定系统夹具的身份，Agent 片段沿用测试显式给出的资源身份。"""
    return PromptCatalog(
        (
            *(
                PromptFragment(ResourceKey("test", "prompt", "system", f"part-{index}"), text)
                for index, text in enumerate(system)
            ),
            *(PromptFragment(ResourceKey.parse(identity), text) for identity, text in agents.items()),
        )
    )
