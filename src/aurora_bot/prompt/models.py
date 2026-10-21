"""保持资源身份、内容版本与装配顺序一致的不可变提示词目录。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurora_bot.contracts.resource import ResourceKey

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurora_bot.contracts.prompt import PromptFragment
    from aurora_bot.contracts.resource import ResourceRef


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    """显式资源片段是唯一来源，文本视图从冻结片段生成。"""

    fragments: tuple[PromptFragment, ...]
    system: tuple[str, ...] = field(init=False)
    agent_prompts: Mapping[str, str] = field(init=False)
    _by_key: Mapping[ResourceKey, PromptFragment] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """拒绝重复身份和缺失的必要类别，不丢弃匿名或空白片段。"""
        fragments = tuple(self.fragments)
        by_key: dict[ResourceKey, PromptFragment] = {}
        for fragment in fragments:
            if fragment.key in by_key:
                raise ValueError(f"提示词资源身份重复：{fragment.key}")
            by_key[fragment.key] = fragment
        system = tuple(fragment.content for fragment in fragments if fragment.key.kind == "system")
        agents = {str(fragment.key): fragment.content for fragment in fragments if fragment.key.kind == "agent"}
        if not system:
            raise ValueError("提示词目录至少需要一个 system 片段")
        if not agents:
            raise ValueError("提示词目录至少需要一个 Agent prompt")
        object.__setattr__(self, "fragments", fragments)
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "agent_prompts", MappingProxyType(agents))
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))

    def get(self, ref: ResourceRef) -> PromptFragment:
        """解析当前目录的确定版本，明确拒绝其他版本。"""
        fragment = self._by_key.get(ref.key)
        if fragment is None or (ref.revision is not None and ref != fragment.ref):
            raise LookupError(f"提示词资源版本不存在：{ref.key}，版本 {ref.revision}")
        return fragment

    def for_agent(self, prompt_id: str) -> tuple[PromptFragment, ...]:
        """按系统片段顺序和节点选定的 Agent 提示词返回实际装配来源。"""
        key = ResourceKey.parse(prompt_id)
        fragment = self._by_key.get(key)
        if fragment is None or key.kind != "agent":
            raise ValueError(f"Agent 提示词不存在：{prompt_id}")
        return (*(part for part in self.fragments if part.key.kind == "system"), fragment)
