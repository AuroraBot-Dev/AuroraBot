"""预定义 Agent 原型的不可变目录。"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from src.contracts import AgentDefinition


class AgentDefinitionError(ValueError):
    """AgentDefinition 集合不能形成封闭、唯一的目录。"""


class AgentCatalog:
    """definition ID → AgentDefinition 的不可变唯一目录。"""

    def __init__(self, definitions: Iterable[AgentDefinition]) -> None:
        by_id: dict[str, AgentDefinition] = {}
        for definition in definitions:
            if definition.definition_id in by_id:
                raise AgentDefinitionError(f"Agent definition 重复注册：{definition.definition_id}")
            by_id[definition.definition_id] = definition
        if not by_id:
            raise AgentDefinitionError("至少需要一个 Agent definition")
        for definition in by_id.values():
            unknown = definition.children - by_id.keys()
            if unknown:
                names = ", ".join(sorted(unknown))
                raise AgentDefinitionError(f"{definition.definition_id} 引用了未知 child Agent：{names}")
        self._definitions: Mapping[str, AgentDefinition] = MappingProxyType(
            {definition_id: by_id[definition_id] for definition_id in sorted(by_id)}
        )

    @property
    def definitions(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._definitions.values())

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._definitions)

    def get(self, definition_id: str) -> AgentDefinition:
        try:
            return self._definitions[definition_id]
        except KeyError as error:
            raise AgentDefinitionError(f"未知 Agent definition：{definition_id}") from error
