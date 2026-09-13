"""``agents`` 暴露的全局端口：Agent 原型目录契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import AgentDefinition


class AgentCatalog(Protocol):
    """definition ID → AgentDefinition 的只读目录。"""

    @property
    def definitions(self) -> tuple[AgentDefinition, ...]: ...

    @property
    def ids(self) -> frozenset[str]: ...

    def get(self, definition_id: str) -> AgentDefinition: ...
