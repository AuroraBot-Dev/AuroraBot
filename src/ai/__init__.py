"""AI 模块的统一入口，导出网关、模型定价和供应商配置的公开 API。

用法::

    from src.ai import gateway, init_gateway
    from src.ai import setup_providers

    setup_providers()
    init_gateway()

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from .gateway import (
    CancelledWithPartialResponse,
    CostTracker,
    GatewayError,
    GenerationTask,
    ModelCaller,
    ModelGateway,
    TaskManager,
    gateway,
    get_gateway,
    init_gateway,
)
from .models import (
    get_pricing_by_id,
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
    "ModelGateway",
    "ProviderConfig",
    "TaskManager",
    "gateway",
    "get_gateway",
    "get_pricing_by_id",
    "init_gateway",
    "resolve_model",
    "setup_providers",
]
