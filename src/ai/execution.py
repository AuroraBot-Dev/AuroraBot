"""LiteLLM streaming execution primitives, cancellation and cost tracking.

用法::

    from src.ai.gateway import gateway

    gen = gateway.fast.acompletion(
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
    )
    response = await gen                     # ModelResponse
    text = gateway.plain(response)           # str
    print(gen.cost)

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import TYPE_CHECKING, Any, Protocol, cast

# ── LiteLLM 环境抑制（必须在 import litellm 前设置） ──
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "False"

import litellm
from litellm import completion_cost, stream_chunk_builder
from litellm.utils import token_counter

litellm.suppress_debug_info = True

from src.ai.models import get_pricing_by_id
from src.ai.providers import missing_credentials_reason, resolve_model
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    import collections.abc

logger = get_logger("Gateway")


class GatewayState(Protocol):
    """Minimal state used by a model caller without importing the gateway facade."""

    log_queries: bool
    log_responses: bool
    cost_tracker: "CostTracker"


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

ROLE_FAST = "fast"
ROLE_QUALITY = "quality"
ROLE_MULTIMODAL = "multimodal"

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


class CancelledWithPartialResponse(asyncio.CancelledError):
    """流式任务被打断时抛出，携带已生成的部分响应与估算费用。"""

    def __init__(self, partial_response: Any, cost: float) -> None:
        super().__init__()
        self.partial_response = partial_response
        self.cost = cost


def _exc_msg() -> str:
    """返回当前异常的简略消息，不打印堆栈。"""
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

    def cancel(self) -> bool:
        return self._task.cancel()

    def done(self) -> bool:
        return self._task.done()

    def plain(self) -> str:
        """从响应中提取纯文本内容，兼容 None → ''。"""
        if self.response is None:
            return ""
        try:
            content = self.response.choices[0].message.content
            return str(content) if content is not None else ""
        except (AttributeError, IndexError, TypeError):
            return ""


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

    def abort(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            logger.debug("Task %s cancelled", task_id)
            return True
        return False

    def abort_all(self) -> None:
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        self._tasks.clear()


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
            raise PermissionError("调用方禁止传入 model 参数，模型由网关角色统一指定")

        async def _safe_cost(
            response: Any,
            prompt_tokens: int = 0,
            completion_tokens: int = 0,
        ) -> float:
            """安全计算费用；litellm 失败时回退到 models.dev 定价。"""
            try:
                return completion_cost(completion_response=response)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "litellm completion_cost failed for model=%s: %s",
                    self.model,
                    _exc_msg(),
                )
                return await _fallback_cost(prompt_tokens, completion_tokens)

        async def _safe_cost_per_token(pt: int, ct: int) -> float:
            """按 token 数计费；litellm 失败时回退到 models.dev 定价。"""
            try:
                cost = litellm.cost_per_token(
                    model=self.model,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                )
                if isinstance(cost, tuple):
                    return float(sum(cost))
                return float(cost)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "litellm cost_per_token failed for model=%s: %s",
                    self.model,
                    _exc_msg(),
                )
                return await _fallback_cost(pt, ct)

        async def _fallback_cost(prompt_tokens: int, completion_tokens: int) -> float:
            """从 models.dev 拉取定价并计算费用，不可用时返回 0.0。"""
            pricing = await get_pricing_by_id(self.model)
            if not pricing:
                return 0.0
            input_price = pricing.get("input", 0)
            output_price = pricing.get("output", 0)
            cost = (prompt_tokens / 1_000_000) * input_price + (completion_tokens / 1_000_000) * output_price
            logger.debug(
                "models.dev fallback cost:\n%s",
                json.dumps(
                    {
                        "model": self.model,
                        "cost": cost,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            return cost

        async def _stream_and_collect() -> tuple[Any, float]:  # noqa: C901, PLR0912, PLR0915
            prompt_tokens = 0

            # 解析自定义供应商 → litellm 原生模型 + 额外参数
            missing_reason = missing_credentials_reason(self.model)
            if missing_reason is not None:
                raise GatewayError(missing_reason, retryable=False)

            resolved_model, provider_kwargs = resolve_model(self.model)

            try:
                prompt_tokens = token_counter(model=resolved_model, messages=messages)
            except Exception:  # noqa: BLE001
                # Token 估算失败不应中断主流程；保留默认值 0，并记录调试信息便于排查。
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
            # 先合并供应商的 api_base / api_key，再合并调用方传入的 kwargs
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
            estimated_completion = 0

            try:
                async for chunk in response_stream:
                    chunks.append(chunk)
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        final_usage = chunk.usage
            except asyncio.CancelledError:
                is_cancelled = True

            cost = 0.0
            final_response: Any = None

            if not is_cancelled:
                final_response = stream_chunk_builder(chunks, messages=messages)
                pt = final_usage.prompt_tokens if final_usage else 0
                ct = final_usage.completion_tokens if final_usage else 0
                cost = await _safe_cost(final_response, pt, ct)
                await self.gateway.cost_tracker.add(
                    {
                        "task_id": None,
                        "role": self.role,
                        "model": self.model,
                        "type": "completion",
                        "status": "completed",
                        "prompt_tokens": (final_usage.prompt_tokens if final_usage else 0),
                        "completion_tokens": (final_usage.completion_tokens if final_usage else 0),
                        "cost": cost,
                    }
                )
                response_text = ""
                try:
                    if final_response is not None:
                        content = final_response.choices[0].message.content
                        response_text = str(content) if content is not None else "<empty>"
                except (AttributeError, IndexError, TypeError):
                    pass

                if self.gateway.log_responses:
                    logger.debug(
                        "LLM 响应:\n%s",
                        json.dumps(
                            {
                                "role": self.role,
                                "cost": cost,
                                "text": response_text,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                else:
                    logger.debug(
                        "LLM 响应:\n%s",
                        json.dumps(
                            {
                                "role": self.role,
                                "cost": cost,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                return final_response, cost
            if final_usage is not None:
                built = stream_chunk_builder(chunks, messages=messages)
                cost = await _safe_cost(
                    built,
                    final_usage.prompt_tokens,
                    final_usage.completion_tokens,
                )
            else:
                estimated_completion = sum(len(c.choices[0].delta.content or "") // 4 for c in chunks if c.choices)
                cost = await _safe_cost_per_token(prompt_tokens, estimated_completion)
            try:
                partial_response = stream_chunk_builder(chunks, messages=messages)
            except Exception:  # noqa: BLE001
                partial_response = None

            await self.gateway.cost_tracker.add(
                {
                    "task_id": None,
                    "role": self.role,
                    "model": self.model,
                    "type": "completion",
                    "status": "cancelled",
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": (final_usage.completion_tokens if final_usage else estimated_completion),
                    "cost": cost,
                }
            )
            raise CancelledWithPartialResponse(partial_response, cost)

        return self.tm.create_task(_stream_and_collect())
