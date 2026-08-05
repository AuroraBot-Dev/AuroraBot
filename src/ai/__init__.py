"""RFC 0104 — AI 模型网关，导出网关、模型查询和供应商配置的公开 API。

模型定价与能力以 models.dev 为第一信息源，
数据缓存于 ``data/ai/`` 目录。

用法::

    from src.ai import ModelGatewayService, init_cache, setup_providers
    from src.ai.models import get_pricing_by_id, get_capabilities_by_id

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from .execution import (
    CancelledWithPartialResponse,
    CostTracker,
    GatewayError,
    GenerationTask,
    ModelCaller,
    TaskManager,
)
from .gateway import ModelGatewayService
from .models import (
    cache_available,
    compute_cost,
    get_capabilities_by_id,
    get_model_info,
    get_pricing_by_id,
    init_cache,
    refresh_now,
)
from .providers import (
    ProviderConfig,
    resolve_model,
    setup_providers,
)

__all__ = [
    "CancelledWithPartialResponse",
    "CostTracker",
    "GatewayError",
    "GenerationTask",
    "ModelCaller",
    "ModelGatewayService",
    "ProviderConfig",
    "TaskManager",
    "cache_available",
    "compute_cost",
    "get_capabilities_by_id",
    "get_model_info",
    "get_pricing_by_id",
    "init_cache",
    "refresh_now",
    "resolve_model",
    "setup_providers",
]
