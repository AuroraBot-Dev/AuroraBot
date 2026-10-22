"""``ai`` 暴露的全局端口：模型调用契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aurora_bot.contracts.model import ChatMessage, ModelRequest
    from aurora_bot.contracts.model_binding import ModelBinding, ProviderDefinition


class Model(Protocol):
    @property
    def providers(self) -> tuple[ProviderDefinition, ...]: ...

    @property
    def endpoints(self) -> tuple[ModelBinding, ...]: ...

    def resolve_endpoint(self, endpoint_id: str) -> ModelBinding:
        """按显式身份返回实际采用的冻结端点，调用前即可记录确定版本。"""
        ...

    async def complete(self, request: ModelRequest) -> ChatMessage: ...
