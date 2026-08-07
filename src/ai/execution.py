"""LiteLLM 流式执行原语、取消机制与成本追踪。

费用计算以 models.dev 为第一（唯一）信息源，不再使用 litellm 内置定价。

用法::

    from src.ai.gateway import ModelGatewayService

    service = ModelGatewayService(config)
    gen = service.fast.acompletion(
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
    )
    response = await gen
    print(gen.cost)

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import TYPE_CHECKING, Any, Protocol, cast

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "False"

import litellm
from litellm import stream_chunk_builder
from litellm.utils import token_counter

litellm.suppress_debug_info = True

from enum import StrEnum

from src.ai.models import compute_cost
from src.ai.providers import missing_credentials_reason, resolve_model
from src.utils import get_logger

if TYPE_CHECKING:
    import collections.abc


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    FORBIDDEN_MODEL_PARAM = "调用方禁止传入 model 参数，模型由网关角色统一指定"


logger = get_logger("Gateway")


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


def _exc_msg() -> str:
    import sys

    e = sys.exc_info()[1]
    return f"{type(e).__name__}: {e}" if e is not None else "unknown"


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
    def __init__(self) -> None:
        self._records: list[dict] = []
        self._lock = asyncio.Lock()

    async def add(self, record: dict) -> None:
        async with self._lock:
            self._records.append(record)

    async def summary(self) -> dict:
        async with self._lock:
            total = 0.0
            by_role: dict[str, dict] = {}
            by_model: dict[str, dict] = {}
            for r in self._records:
                total += r.get("cost", 0.0)
                role = r["role"]
                model = r["model"]
                if role not in by_role:
                    by_role[role] = {"count": 0, "cost": 0.0}
                by_role[role]["count"] += 1
                by_role[role]["cost"] += r.get("cost", 0.0)
                if model not in by_model:
                    by_model[model] = {"count": 0, "cost": 0.0}
                by_model[model]["count"] += 1
                by_model[model]["cost"] += r.get("cost", 0.0)
            return {
                "total_cost": total,
                "by_role": by_role,
                "by_model": by_model,
                "records": list(self._records),
            }


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


# ═══════════════════════════════════════════════════════════
# 模型调用器
# ═══════════════════════════════════════════════════════════


class ModelCaller:
    def __init__(
        self,
        model: str,
        role: str,
        task_manager: TaskManager,
        gateway: GatewayState,
    ) -> None:
        self.model = model
        self.role = role
        self.tm = task_manager
        self.gateway = gateway

    def acompletion(  # noqa: C901, PLR0915
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 2048,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> GenerationTask:
        """强制流式对话，返回可 ``await`` 的 :class:`GenerationTask`。

        禁止调用方传入 ``model`` 参数 —— 模型由角色配置统一指定。
        """
        if "model" in kwargs:
            raise PermissionError(_Msg.FORBIDDEN_MODEL_PARAM)

        async def _compute_and_track(
            prompt_tokens: int,
            completion_tokens: int,
            status: str = "completed",
        ) -> float:
            """费用计算第一信息源：models.dev。"""
            try:
                cost = await compute_cost(self.model, prompt_tokens, completion_tokens)
            except Exception:  # noqa: BLE001
                logger.warning("models.dev 费用计算失败 model=%s: %s", self.model, _exc_msg())
                cost = 0.0
            await self.gateway.cost_tracker.add(
                {
                    "task_id": None,
                    "role": self.role,
                    "model": self.model,
                    "type": "completion",
                    "status": status,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost": cost,
                }
            )
            return cost

        async def _stream_and_collect() -> tuple[Any, float]:  # noqa: C901, PLR0912, PLR0915
            prompt_tokens = 0

            missing_reason = missing_credentials_reason(self.model)
            if missing_reason is not None:
                raise GatewayError(missing_reason, retryable=False)

            resolved_model, provider_kwargs = resolve_model(self.model)

            try:
                prompt_tokens = token_counter(model=resolved_model, messages=messages)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "token_counter failed for model=%s; fallback prompt_tokens=0",
                    resolved_model,
                    exc_info=True,
                )

            litellm_kwargs: dict[str, Any] = {
                "model": resolved_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if timeout is not None:
                litellm_kwargs["timeout"] = timeout
            litellm_kwargs.update(provider_kwargs)
            litellm_kwargs.update(kwargs)

            if self.gateway.log_queries:
                logger.debug(
                    "LLM 请求:\n%s",
                    json.dumps(
                        {
                            "role": self.role,
                            "model": self.model,
                            "messages_count": len(messages),
                            "max_tokens": max_tokens,
                            "timeout": timeout,
                            "messages": [
                                {"role": m.get("role", "?"), "content": m.get("content", "<empty>")} for m in messages
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            else:
                logger.debug(
                    "LLM 请求:\n%s",
                    json.dumps(
                        {
                            "role": self.role,
                            "model": self.model,
                            "messages_count": len(messages),
                            "max_tokens": max_tokens,
                            "timeout": timeout,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

            try:
                response = await litellm.acompletion(**litellm_kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _classify_exception(exc) from exc

            response_stream = cast("collections.abc.AsyncIterable[Any]", response)
            chunks: list = []
            final_usage: Any = None
            is_cancelled = False

            try:
                async for chunk in response_stream:
                    chunks.append(chunk)
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        final_usage = chunk.usage
            except asyncio.CancelledError:
                is_cancelled = True

            if not is_cancelled:
                final_response = stream_chunk_builder(chunks, messages=messages)
                pt = final_usage.prompt_tokens if final_usage else 0
                ct = final_usage.completion_tokens if final_usage else 0
                cost = await _compute_and_track(pt, ct, "completed")

                response_text = ""
                try:
                    if final_response is not None:
                        content = final_response.choices[0].message.content  # type: ignore[attr-defined]
                        response_text = str(content) if content is not None else "<empty>"
                except (AttributeError, IndexError, TypeError):
                    pass

                if self.gateway.log_responses:
                    logger.debug(
                        "LLM 响应:\n%s",
                        json.dumps(
                            {"role": self.role, "cost": cost, "text": response_text},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                else:
                    logger.debug(
                        "LLM 响应:\n%s",
                        json.dumps({"role": self.role, "cost": cost}, ensure_ascii=False, indent=2),
                    )
                return final_response, cost

            # 被取消：记录已生成 token 的费用后继续传播取消
            if final_usage is not None:
                await _compute_and_track(final_usage.prompt_tokens, final_usage.completion_tokens, "cancelled")
            else:
                completion_tokens = sum(len(c.choices[0].delta.content or "") // 4 for c in chunks if c.choices)
                await _compute_and_track(prompt_tokens, completion_tokens, "cancelled")
            raise asyncio.CancelledError

        return self.tm.create_task(_stream_and_collect())
