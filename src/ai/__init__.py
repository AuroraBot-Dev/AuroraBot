"""AI 模型网关公开 API。

模型定价与能力以 models.dev 为第一信息源，数据缓存于 ``data/ai/`` 目录。
"""

from src.ai.gateway import ModelGatewayService

__all__ = ["ModelGatewayService"]
