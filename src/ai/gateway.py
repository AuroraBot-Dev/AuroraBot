"""Role-based model gateway facade with explicit initialization."""

from collections.abc import Mapping
from typing import Any

from src.ai.execution import (
    CancelledWithPartialResponse,
    CostTracker,
    GatewayError,
    GenerationTask,
    ModelCaller,
    TaskManager,
)
from src.utils.log_utils import get_logger

logger = get_logger("Gateway")

ROLE_FAST = "fast"
ROLE_QUALITY = "quality"
ROLE_MULTIMODAL = "multimodal"


class ModelGateway:
    """Map configured model roles to streaming execution callers."""

    def __init__(
        self,
        fast: str | None = None,
        quality: str | None = None,
        multimodal: str | None = None,
        embedding: str = "",
        reranker: str = "",
        *,
        models: Mapping[str, str] | None = None,
        log_queries: bool = False,
        log_responses: bool = False,
    ) -> None:
        if models is None:
            if fast is None or quality is None or multimodal is None:
                raise ValueError("fast, quality and multimodal are required without models")
            self._models = {ROLE_FAST: fast, ROLE_QUALITY: quality, ROLE_MULTIMODAL: multimodal}
        else:
            self._models = dict(models)
        for role, model in self._models.items():
            if "/" not in model:
                raise ValueError(f"Model for role '{role}' must be in 'provider/model_name' format, got '{model}'")
        self.embedding = embedding
        self.reranker = reranker
        self.log_queries = log_queries
        self.log_responses = log_responses
        self.task_manager = TaskManager()
        self.cost_tracker = CostTracker()
        self._callers = {
            role: ModelCaller(model, role, self.task_manager, self) for role, model in self._models.items()
        }

    def use_model(self, role: str) -> ModelCaller:
        role = role.lower()
        if role not in self._callers:
            raise ValueError(f"Unknown role '{role}'. Available: {list(self._callers)}")
        return self._callers[role]

    @property
    def fast(self) -> ModelCaller:
        return self.use_model(ROLE_FAST)

    @property
    def quality(self) -> ModelCaller:
        return self.use_model(ROLE_QUALITY)

    @property
    def multimodal(self) -> ModelCaller:
        return self.use_model(ROLE_MULTIMODAL)

    @staticmethod
    def plain(response: Any) -> str:
        if response is None:
            return ""
        try:
            content = response.choices[0].message.content
            return str(content) if content is not None else ""
        except (AttributeError, IndexError, TypeError):
            return ""

    def abort_task(self, task_id: str) -> bool:
        return self.task_manager.abort(task_id)

    def abort_all(self) -> None:
        self.task_manager.abort_all()

    def export_config(self) -> dict[str, str]:
        config = {role: caller.model for role, caller in self._callers.items()}
        if self.embedding:
            config["embedding"] = self.embedding
        if self.reranker:
            config["reranker"] = self.reranker
        return config

    async def cost_summary(self) -> dict[str, Any]:
        return await self.cost_tracker.summary()


_singleton: ModelGateway | None = None


def init_gateway(
    fast: str,
    quality: str,
    multimodal: str,
    embedding: str = "",
    reranker: str = "",
    *,
    log_queries: bool = False,
    log_responses: bool = False,
) -> ModelGateway:
    """Initialize the optional process-wide facade explicitly."""
    global _singleton  # noqa: PLW0603
    _singleton = ModelGateway(
        fast,
        quality,
        multimodal,
        embedding,
        reranker,
        log_queries=log_queries,
        log_responses=log_responses,
    )
    logger.info("model execution gateway initialized roles=%s", sorted(_singleton.export_config()))
    return _singleton


def get_gateway() -> ModelGateway:
    if _singleton is None:
        raise RuntimeError("model gateway is not initialized")
    return _singleton


class _GatewayProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_gateway(), name)


gateway = _GatewayProxy()

__all__ = [
    "CancelledWithPartialResponse",
    "CostTracker",
    "GatewayError",
    "GenerationTask",
    "ModelCaller",
    "ModelGateway",
    "TaskManager",
    "gateway",
    "get_gateway",
    "init_gateway",
]
