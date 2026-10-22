"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts.prompt import PromptFragment
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.prompt import PromptCatalog

if TYPE_CHECKING:
    from collections.abc import Mapping
from aurora_bot.contracts import (
    AgentDefinition,
)
from aurora_bot.prompt import PromptAssembler


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
    )
