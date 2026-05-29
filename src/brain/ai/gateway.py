"""LiteLLM 统一模型网关 —— 多角色、流式打断、费用追踪、异常分类。

用法::

    from src.brain.ai.gateway import gateway

    gen = gateway.fast.acompletion(
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
    )
    response = await gen                     # ModelResponse
    text = gateway.plain(response)           # str
    print(gen.cost)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional, Union

# ── LiteLLM 环境抑制（必须在 import litellm 前设置） ──
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "False"

import litellm
from litellm import completion_cost, stream_chunk_builder
from litellm.utils import token_counter

litellm.suppress_debug_info = True

from src.utils.log_utils import get_logger

logger = get_logger("Gateway")

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

ROLE_FAST = "fast"
ROLE_QUALITY = "quality"
ROLE_MULTIMODAL = "multimodal"
ROLE_EMBEDDING = "embedding"

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


def _classify_exception(exc: Exception) -> GatewayError:
    """将 litellm 原始异常转换为带 retryable 标记的 GatewayError。"""
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

    def summary(self) -> dict:
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
            "records": self._records,
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

    def __await__(self):
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
        self._tasks: Dict[str, asyncio.Task] = {}

    def create_task(self, coro) -> GenerationTask:
        task_id = uuid.uuid4().hex[:8]
        task = asyncio.create_task(coro)
        self._tasks[task_id] = task
        task.add_done_callback(lambda t: self._tasks.pop(task_id, None))
        return GenerationTask(task_id, task)

    def abort(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Task {task_id} cancelled")
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
        gateway: "ModelGateway",
    ) -> None:
        self.model = model
        self.role = role
        self.tm = task_manager
        self.gateway = gateway

    def acompletion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 2048,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> GenerationTask:
        """强制流式对话，返回可 ``await`` 的 :class:`GenerationTask`。

        禁止调用方传入 ``model`` 参数 —— 模型由角色配置统一指定。
        """
        if self.role == ROLE_EMBEDDING:
            raise ValueError("Embedding model cannot be used for chat completions.")

        if "model" in kwargs:
            raise PermissionError("调用方禁止传入 model 参数，模型由网关角色统一指定")

        def _safe_cost(response: Any, /) -> float:
            """安全计算费用，失败时返回 0.0 并记录 warning（不含堆栈）。"""
            try:
                return completion_cost(completion_response=response)
            except Exception:
                logger.warning(
                    "Cost calculation failed for model=%s: %s",
                    self.model,
                    _exc_msg(),
                )
                return 0.0

        def _safe_cost_per_token(pt: int, ct: int, /) -> float:
            try:
                return litellm.cost_per_token(
                    model=self.model,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                )
            except Exception:
                logger.warning(
                    "cost_per_token failed for model=%s: %s",
                    self.model,
                    _exc_msg(),
                )
                return 0.0

        async def _stream_and_collect() -> tuple[Any, float]:
            prompt_tokens = 0
            try:
                prompt_tokens = token_counter(model=self.model, messages=messages)
            except Exception:
                pass

            litellm_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if timeout is not None:
                litellm_kwargs["timeout"] = timeout
            litellm_kwargs.update(kwargs)

            logger.info(
                f"LLM 请求: role={self.role} model={self.model} "
                f"messages_count={len(messages)} max_tokens={max_tokens} "
                f"timeout={timeout}"
            )

            try:
                response = await litellm.acompletion(**litellm_kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _classify_exception(exc) from exc

            chunks: list = []
            final_usage: Any = None
            is_cancelled = False

            try:
                async for chunk in response:
                    chunks.append(chunk)
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        final_usage = chunk.usage
            except asyncio.CancelledError:
                is_cancelled = True

            cost = 0.0
            final_response: Any = None

            if not is_cancelled:
                final_response = stream_chunk_builder(chunks, messages=messages)
                cost = _safe_cost(final_response)
                await self.gateway.cost_tracker.add(
                    {
                        "task_id": None,
                        "role": self.role,
                        "model": self.model,
                        "type": "completion",
                        "status": "completed",
                        "prompt_tokens": (
                            final_usage.prompt_tokens if final_usage else 0
                        ),
                        "completion_tokens": (
                            final_usage.completion_tokens if final_usage else 0
                        ),
                        "cost": cost,
                    }
                )
                content = (
                    final_response.choices[0].message.content
                    if final_response and final_response.choices
                    else "<empty>"
                )
                logger.info(
                    f"LLM 响应: role={self.role} cost=${cost:.6f} "
                    f"{str(content)[:200] if content else '<empty>'}"
                )
                return final_response, cost
            else:
                if final_usage is not None:
                    cost = _safe_cost(stream_chunk_builder(chunks, messages=messages))
                else:
                    estimated_completion = sum(
                        len(c.choices[0].delta.content or "") // 4
                        for c in chunks
                        if c.choices
                    )
                    cost = _safe_cost_per_token(prompt_tokens, estimated_completion)
                try:
                    partial_response = stream_chunk_builder(chunks, messages=messages)
                except Exception:
                    partial_response = None

                await self.gateway.cost_tracker.add(
                    {
                        "task_id": None,
                        "role": self.role,
                        "model": self.model,
                        "type": "completion",
                        "status": "cancelled",
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": (
                            final_usage.completion_tokens
                            if final_usage
                            else estimated_completion
                        ),
                        "cost": cost,
                    }
                )
                raise CancelledWithPartialResponse(partial_response, cost)

        return self.tm.create_task(_stream_and_collect())

    async def aembedding(self, input: Union[str, List[str]], **kwargs: Any) -> Any:
        if self.role != ROLE_EMBEDDING:
            raise ValueError(
                f"Model {self.model} with role '{self.role}' does not support embeddings."
            )
        if isinstance(input, str):
            input = [input]

        logger.info(
            f"LLM 请求: role={self.role} model={self.model} "
            f"embedding input_count={len(input)}"
        )

        try:
            response = await litellm.aembedding(model=self.model, input=input, **kwargs)
        except Exception as exc:
            raise _classify_exception(exc) from exc

        cost = 0.0
        # embedding_cost 在当前 litellm 版本不可用，保留占位
        # try:
        #     cost = embedding_cost(embedding_response=response)
        # except Exception:
        #     logger.warning("Embedding cost failed", exc_info=True)

        await self.gateway.cost_tracker.add(
            {
                "task_id": None,
                "role": self.role,
                "model": self.model,
                "type": "embedding",
                "status": "completed",
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": 0,
                "cost": cost,
            }
        )
        logger.info(
            f"LLM 响应: role={self.role} embedding "
            f"tokens={response.usage.prompt_tokens} cost=${cost:.6f}"
        )
        return response


# ═══════════════════════════════════════════════════════════
# 统一网关
# ═══════════════════════════════════════════════════════════


class ModelGateway:
    """多角色模型网关。

    用法::

        gateway = ModelGateway(
            fast="deepseek/deepseek-v4-flash",
            quality="deepseek/deepseek-v4-pro",
            multimodal="openai/gpt-4o",
            embedding="openai/text-embedding-3-small",
        )
        gen = gateway.fast.acompletion(messages=[...])
        resp = await gen
        text = gen.plain()
    """

    def __init__(
        self, fast: str, quality: str, multimodal: str, embedding: str
    ) -> None:
        self._models = {
            ROLE_FAST: fast,
            ROLE_QUALITY: quality,
            ROLE_MULTIMODAL: multimodal,
            ROLE_EMBEDDING: embedding,
        }
        for role, model in self._models.items():
            if "/" not in model:
                raise ValueError(
                    f"Model for role '{role}' must be in "
                    f"'provider/model_name' format, got '{model}'"
                )

        self.task_manager = TaskManager()
        self.cost_tracker = CostTracker()

        self._callers: dict[str, ModelCaller] = {
            role: ModelCaller(model, role, self.task_manager, self)
            for role, model in self._models.items()
        }

    def use_model(self, role: str) -> ModelCaller:
        role = role.lower()
        if role not in self._callers:
            raise ValueError(
                f"Unknown role '{role}'. " f"Available: {list(self._callers.keys())}"
            )
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

    @property
    def embedding(self) -> ModelCaller:
        return self.use_model(ROLE_EMBEDDING)

    @staticmethod
    def plain(response: Any) -> str:
        """从 ModelResponse 提取纯文本内容。

        兼容: ``gateway.plain(response)`` 或 ``gen.plain()``
        （GenerationTask 上已有同名实例方法）。
        """
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
        return {role: caller.model for role, caller in self._callers.items()}

    def cost_summary(self) -> dict:
        """获取费用分类汇总。"""
        return self.cost_tracker.summary()


# ═══════════════════════════════════════════════════════════
# 模块单例（延迟初始化）
# ═══════════════════════════════════════════════════════════

_singleton: ModelGateway | None = None


def init_gateway(
    fast: str,
    quality: str,
    multimodal: str,
    embedding: str,
) -> ModelGateway:
    """初始化模块单例。项目启动时调用一次。"""
    global _singleton
    _singleton = ModelGateway(
        fast=fast,
        quality=quality,
        multimodal=multimodal,
        embedding=embedding,
    )
    logger.info(f"网关已初始化: {_singleton.export_config()}")
    return _singleton


def get_gateway() -> ModelGateway:
    """获取模块单例。若未初始化则从 Config 读取默认值自动初始化。"""
    global _singleton
    if _singleton is None:
        from src.config import Config

        _singleton = init_gateway(
            fast=Config.LLM_GATEWAY_FAST_MODEL,
            quality=Config.LLM_GATEWAY_QUALITY_MODEL,
            multimodal=Config.LLM_GATEWAY_MULTIMODAL_MODEL,
            embedding=Config.LLM_GATEWAY_EMBEDDING_MODEL,
        )
    return _singleton


# 便捷别名 —— 大多数场景直接 ``from src.brain.ai.gateway import gateway``
gateway: ModelGateway = get_gateway()
