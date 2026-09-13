"""``ai`` 暴露的全局端口：模型调用契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.contracts.model import ChatMessage, ModelRequest


class Model(Protocol):
    """AgentTree 循环使用的唯一模型端口。"""

    async def complete(self, request: ModelRequest) -> ChatMessage: ...
