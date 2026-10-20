"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurorabot.contracts.prompt import PromptFragment
from aurorabot.contracts.resource import ResourceKey
from aurorabot.prompt import PromptCatalog

if TYPE_CHECKING:
    from collections.abc import Mapping
from aurorabot.contracts import (
    AgentDefinition,
)
from aurorabot.prompt import PromptAssembler


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


def _assembler(*, limit: int = 1_000) -> PromptAssembler:
    return PromptAssembler(
        make_prompt_catalog(
            ("You are Aurora.", "The world continues between messages."),
            {"aurora:prompt/agent/root": "Act as the root."},
        ),
        max_characters=limit,
    )


def _agent(prompt: str = "aurora:prompt/agent/root") -> AgentDefinition:
    return AgentDefinition(
        "aurora:agent/definition/test",
        "Test Agent.",
        prompt,
        "test:ai/endpoint/quality-model",
        frozenset(),
        frozenset(),
    )
