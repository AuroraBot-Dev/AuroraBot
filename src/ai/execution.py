"""网关执行原语：异常分类、费用记录器与任务包装（角色 ChatCaller 依赖的共享层）。

费用计算以 models.dev 为第一（唯一）信息源，不再使用 litellm 内置定价。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import TYPE_CHECKING, Any, Protocol

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "False"

import litellm

litellm.suppress_debug_info = True

from src.utils import get_logger

if TYPE_CHECKING:
    import collections.abc

    from src.ai.cost_store import CostStore


logger = get_logger("aurora.ai.execution")


class GatewayState(Protocol):
    """模型调用方使用的最小状态，无需导入网关门面。"""

    log_queries: bool
    log_responses: bool
    cost_tracker: "CostTracker"


# ═══════════════════════════════════════════════════════════
# 异常体系
# ═══════════════════════════════════════════════════════════

_RETRYABLE_EXCEPTIONS = (
    litellm.exceptions.Timeout,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
)


class GatewayError(Exception):
    """统一网关异常，携带 ``retryable`` 标志供调用方决策是否重试。"""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _classify_exception(exc: Exception) -> GatewayError:  # noqa: PLR0911
    """将 litellm 原始异常转换为带 retryable 标记的 GatewayError。"""
    if "Missing credentials" in str(exc):
        return GatewayError(f"LLM 凭证缺失: {exc}", retryable=False)
    if isinstance(exc, litellm.exceptions.AuthenticationError):
        return GatewayError(f"LLM 认证失败: {exc}", retryable=False)
    if isinstance(exc, litellm.exceptions.BadRequestError):
        return GatewayError(f"LLM 请求参数错误: {exc}", retryable=False)
    if isinstance(exc, litellm.exceptions.APIError):
        return GatewayError(f"LLM API 错误: {exc}", retryable=True)
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return GatewayError(f"LLM 调用失败（可重试）: {exc}", retryable=True)
    if isinstance(exc, litellm.exceptions.UnsupportedParamsError):
        return GatewayError(f"LLM 不支持的参数: {exc}", retryable=False)
    return GatewayError(
        f"LLM 调用发生未预期错误: {type(exc).__name__}: {exc}",
        retryable=False,
    )


# ═══════════════════════════════════════════════════════════
# 费用记录器
# ═══════════════════════════════════════════════════════════


class CostTracker:
    """调用费用记录与分类统计（RFC 0215：追踪所有完成的模型调用总费用）。

    内存缓存 + SQLite 追加持久化：启动时经 ``CostStore`` 恢复历史，
    ``add`` 同步写库，统计接口保持内存查询。
    """

    def __init__(self, store: "CostStore | None" = None) -> None:
        self._store = store
        self._records: list[dict] = list(store.load_records()) if store is not None else []
        self._lock = asyncio.Lock()

    async def add(self, record: dict) -> None:
        async with self._lock:
            self._records.append(record)
            if self._store is not None:
                self._store.append(record)

    async def total_cost(self) -> float:
        """全部已完成调用的总费用（USD）。"""
        async with self._lock:
            return round(sum(r.get("cost", 0.0) for r in self._records), 6)

    async def by_role(self) -> dict[str, dict]:
        """按角色分类统计。"""
        async with self._lock:
            return _aggregate(self._records, "role")

    async def by_model(self) -> dict[str, dict]:
        """按模型分类统计。"""
        async with self._lock:
            return _aggregate(self._records, "model")

    async def by_status(self) -> dict[str, dict]:
        """按调用状态分类统计（completed/cancelled）。"""
        async with self._lock:
            return _aggregate(self._records, "status")

    async def summary(self) -> dict:
        """汇总：总费用 + 角色/模型分类 + 原始记录。"""
        async with self._lock:
            return {
                "total_cost": round(sum(r.get("cost", 0.0) for r in self._records), 6),
                "by_role": _aggregate(self._records, "role"),
                "by_model": _aggregate(self._records, "model"),
                "records": list(self._records),
            }


def _aggregate(records: list[dict], key: str) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for record in records:
        value = str(record.get(key, "unknown"))
        group = grouped.setdefault(value, {"count": 0, "cost": 0.0})
        group["count"] += 1
        group["cost"] += record.get("cost", 0.0)
    return grouped


# ═══════════════════════════════════════════════════════════
# 可等待的任务包装
# ═══════════════════════════════════════════════════════════


class GenerationTask:
    """``await`` 返回完整 ModelResponse；``.cost`` 取单次费用；``.task_id`` 可打断。"""

    def __init__(self, task_id: str, task: asyncio.Task) -> None:
        self.task_id = task_id
        self._task = task
        self.cost = 0.0
        self.response: Any = None

    def __await__(self):  # noqa: ANN204
        result = yield from self._task.__await__()
        self.response, self.cost = result
        return self.response

    def done(self) -> bool:
        return self._task.done()


# ═══════════════════════════════════════════════════════════
# 任务管理器
# ═══════════════════════════════════════════════════════════


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def create_task(self, coro: collections.abc.Coroutine[Any, Any, Any]) -> GenerationTask:
        task_id = uuid.uuid4().hex[:8]

        async def _run_and_cleanup() -> Any:
            try:
                return await coro
            finally:
                self._tasks.pop(task_id, None)

        task = asyncio.create_task(_run_and_cleanup())
        self._tasks[task_id] = task
        return GenerationTask(task_id, task)
