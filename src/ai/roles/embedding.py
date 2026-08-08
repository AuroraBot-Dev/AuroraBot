"""预设角色（RFC 0215）：embedding = 词嵌入通道。

第四类基础角色：将文本批量转换为向量，供记忆检索等场景使用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import litellm

from src.ai.providers import resolve_model
from src.ai.roles.base import RoleHandler
from src.contracts import ModelResult, ModelUsage
from src.utils import get_logger

if TYPE_CHECKING:
    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest

logger = get_logger("aurora.ai.roles.embedding")


class EmbeddingRole(RoleHandler):
    """词嵌入角色：``litellm.aembedding`` 批量向量化。"""

    endpoint = "embeddings"
    capability_baseline = frozenset({"embedding"})

    async def embed(
        self,
        gateway: "ModelGatewayService",
        inputs: list[str],
    ) -> list[list[float]]:
        """将文本列表转为向量列表。"""
        model_id = gateway._models.get("embedding") or next(iter(gateway._models.values()))
        resolved_model, provider_kwargs = resolve_model(model_id)
        try:
            response = await litellm.aembedding(
                model=resolved_model,
                input=inputs,
                **provider_kwargs,
            )
        except Exception as error:
            logger.warning("embedding request failed model=%s error_type=%s", model_id, type(error).__name__)
            raise
        data = getattr(response, "data", None)
        if not isinstance(data, list):
            return []
        vectors: list[list[float]] = []
        for item in data:
            embedding = getattr(item, "embedding", None)
            if isinstance(embedding, list) and all(isinstance(value, (int, float)) for value in embedding):
                vectors.append([float(value) for value in embedding])
        return vectors

    async def complete(
        self,
        gateway: "ModelGatewayService",
        request: "ModelRequest",
        role: "ModelRoleConfig",  # noqa: ARG002 - 保持契约签名
        negotiated: frozenset[str],
    ) -> ModelResult:
        """embeddings 通道的 complete 形状：向量放入 data，文本为空。"""
        inputs = [message.content for message in request.messages if isinstance(message.content, str)]
        vectors = await self.embed(gateway, inputs)
        return ModelResult(
            model=gateway._models.get(request.role, ""),
            negotiated_capabilities=negotiated,
            response_mode="normalized",
            text="",
            data={"embeddings": vectors},
            usage=ModelUsage(len(vectors), 0),
            cost_usd=0.0,
            diagnostics=(),
            tool_calls=(),
            finish_reason="completed",
            continuation=None,
        )
