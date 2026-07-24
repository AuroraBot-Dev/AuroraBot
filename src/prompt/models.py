"""不可变提示词目录与分层装配 DTO。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.contracts.model import ModelMessage

# 校验错误消息常量
_INVALID_SECTION = "prompt sections require a key and non-empty content"
_INVALID_CATALOG = "prompt catalog requires string soul and non-empty world"
_INVALID_AGENT_PROMPTS = "prompt catalog requires non-empty Agent prompts"

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class PromptSource:
    """提示词来源快照：文件路径和 SHA-256 摘要。

    PromptSource object::

        {
            "path": "/path/to/file",
            "sha256": "hex-digest"
        }

    """

    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    """不可变提示词目录：soul、world、按 Agent 档案索引的提示词和来源链。

    PromptCatalog object::

        {
            "soul": "string",
            "world": "string",
            "agents": {"profile_id": "prompt text", ...},
            "sources": [PromptSource, ...]
        }

    """

    soul: str
    world: str
    agents: Mapping[str, str]
    sources: tuple[PromptSource, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.soul, str) or not isinstance(self.world, str) or not self.world.strip():
            raise ValueError(_INVALID_CATALOG)
        agents = dict(self.agents)
        invalid = any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value.strip()
            for key, value in agents.items()
        )
        if not agents or invalid:
            raise ValueError(_INVALID_AGENT_PROMPTS)
        object.__setattr__(self, "agents", MappingProxyType(agents))
        object.__setattr__(self, "sources", tuple(self.sources))

    @classmethod
    def create(
        cls,
        *,
        soul: str,
        world: str,
        agents: Mapping[str, str],
        sources: tuple[PromptSource, ...] = (),
    ) -> "PromptCatalog":
        """工厂方法：创建校验通过的 PromptCatalog 实例。"""
        return cls(soul, world, agents, sources)


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
            raise ValueError(_INVALID_SECTION)


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "system_sections", tuple(self.system_sections))
        object.__setattr__(self, "user_sections", tuple(self.user_sections))

    @property
    def system_prompt(self) -> str:
        """将 system sections 拼接为完整 system prompt。"""
        return "\n\n".join(section.content.strip() for section in self.system_sections)

    @property
    def user_prompt(self) -> str:
        """将 user sections 拼接为完整 user prompt。"""
        return "\n\n".join(section.content.strip() for section in self.user_sections)

    def messages(self) -> tuple[ModelMessage, ModelMessage]:
        """转换为标准模型消息对 (system, user)。"""
        return ModelMessage("system", self.system_prompt), ModelMessage("user", self.user_prompt)
