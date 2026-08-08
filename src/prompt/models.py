"""不可变提示词目录与分层装配 DTO。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.contracts import ModelMessage


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    INVALID_SECTION = "prompt sections require a key and non-empty content"
    INVALID_CATALOG = "prompt catalog requires string soul and non-empty world"
    INVALID_AGENT_PROMPTS = "prompt catalog requires non-empty Agent prompts"


if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.configuration import ConfigurationSource, PromptConfig


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    """不可变提示词目录：soul、world、按 Agent 档案索引的提示词和来源链。

    PromptCatalog object::

        {
            "soul": "string",
            "world": "string",
            "agents": {"profile_id": "prompt text", ...},
            "sources": [ConfigurationSource, ...]
        }

    """

    soul: str
    world: str
    agents: Mapping[str, str]
    sources: tuple[ConfigurationSource, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.soul, str) or not isinstance(self.world, str) or not self.world.strip():
            raise ValueError(_Msg.INVALID_CATALOG)
        agents = dict(self.agents)
        invalid = any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value.strip()
            for key, value in agents.items()
        )
        if not agents or invalid:
            raise ValueError(_Msg.INVALID_AGENT_PROMPTS)
        object.__setattr__(self, "agents", MappingProxyType(agents))
        object.__setattr__(self, "sources", tuple(self.sources))

    @classmethod
    def create(
        cls,
        *,
        soul: str,
        world: str,
        agents: Mapping[str, str],
        sources: tuple[ConfigurationSource, ...] = (),
    ) -> "PromptCatalog":
        """工厂方法：创建校验通过的 PromptCatalog 实例。"""
        return cls(soul, world, agents, sources)

    @classmethod
    def from_config(cls, config: PromptConfig) -> "PromptCatalog":
        """从启动时不可变配置创建提示词目录。"""
        return cls(config.soul, config.world, config.agents, config.sources)


@dataclass(frozen=True, slots=True)
class PromptSection:
    """提示词片段：由 key 标识，content 不可为空。

    PromptSection object::

        {
            "key": "string",
            "content": "string"
        }

    """

    key: str
    content: str

    def __post_init__(self) -> None:
        if not self.key or not self.content.strip():
            raise ValueError(_Msg.INVALID_SECTION)


@dataclass(frozen=True, slots=True)
class PromptDocument:
    """一份完整的提示词文档，包含 system 和 user 两类 sections。

    PromptDocument object::

        {
            "system_sections": [PromptSection, ...],
            "user_sections": [PromptSection, ...]
        }

    """

    system_sections: tuple[PromptSection, ...]
    user_sections: tuple[PromptSection, ...]
    memory_system_sections: tuple[PromptSection, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "system_sections", tuple(self.system_sections))
        object.__setattr__(self, "user_sections", tuple(self.user_sections))
        object.__setattr__(self, "memory_system_sections", tuple(self.memory_system_sections))

    @property
    def system_prompt(self) -> str:
        """将 system sections 拼接为完整 system prompt。"""
        return "\n\n".join(section.content.strip() for section in self.system_sections)

    @property
    def user_prompt(self) -> str:
        """将 user sections 拼接为完整 user prompt。"""
        return "\n\n".join(section.content.strip() for section in self.user_sections)

    @property
    def memory_system_prompt(self) -> str:
        """将压缩记忆拼接为独立的 system prompt。"""
        return "\n\n".join(section.content.strip() for section in self.memory_system_sections)

    def messages(self) -> tuple[ModelMessage, ...]:
        """转换为 stable system、可选 memory system 和 user。"""
        messages = [ModelMessage("system", self.system_prompt)]
        if self.memory_system_prompt:
            messages.append(ModelMessage("system", self.memory_system_prompt))
        messages.append(ModelMessage("user", self.user_prompt))
        return tuple(messages)
