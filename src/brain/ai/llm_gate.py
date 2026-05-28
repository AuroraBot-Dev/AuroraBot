from __future__ import annotations
import os
from typing import Any, Dict, List

# 禁用 LiteLLM 远程模型成本图获取，避免网络超时警告。
# 必须在 import litellm 之前设置。
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm
from litellm import acompletion

# 进一步抑制 LiteLLM 的调试信息
litellm.suppress_debug_info = True

from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("LLMGate")

_RETRYABLE_EXCEPTIONS = (
    litellm.exceptions.Timeout,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
)


class LLMGateError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable


async def llm_chat(
    messages: List[Dict[str, str]],
    max_tokens: int = 2048,
    timeout: float | None = None,
    **kwargs: Any,
) -> str:
    """使用 litellm 异步接口调用 LLM，返回模型生成的文本内容。

    TODO 暂时不得传入 model 参数

    TODO 后续需要补充通过协程协作打断请求的说明
    当前打断机制在 :meth:`Agent.cancel_think` 层面实现，通过取消
    包裹 ``llm_chat`` 的 asyncio Task 来中断请求以节省 token。

    本函数是项目内所有 LLM 调用的唯一入口。调用方（agents）不得自行
    选择或切换模型 —— 传入 ``model`` 参数将直接触发 ``PermissionError``。

    Parameters
    ----------
    messages : List[Dict[str, str]]
        符合 OpenAI Chat Completions 格式的消息列表，每条消息须包含
        ``role`` 和 ``content`` 字段。
    max_tokens : int
        模型输出的最大 token 数，默认 2048。
    timeout : float | None
        请求超时秒数，默认 None（由 litellm 内部超时决定）。
        推荐传入 ``Config.LLM_TIMEOUT`` 或 ``Config.LLM_GATE_TIMEOUT``。
    **kwargs : Any
        透传给 ``litellm.acompletion`` 的额外参数（temperature、top_p 等）。
        ``model`` 参数被显式禁止，传入即抛出 ``PermissionError``。

    Returns
    -------
    str
        模型返回的纯文本内容（``response.choices[0].message.content``）。

    Raises
    ------
    ValueError
        ``Config.LITELLM_MODEL`` 为空或未配置时抛出。
    PermissionError
        调用方通过 ``**kwargs`` 传入了 ``model`` 参数时抛出。
    LLMGateError
        所有来自 litellm 的异常（APIError、Timeout、RateLimitError 等）
        均被统一转换为本异常类型，并附带 ``retryable`` 标志。

    Examples
    --------
    >>> import asyncio
    >>> from src.brain.ai.llm_gate import llm_chat
    >>> result = asyncio.run(llm_chat([
    ...     {"role": "system", "content": "你是一个有用的助手。"},
    ...     {"role": "user", "content": "你好，请用一句话介绍你自己。"},
    ... ]))
    >>> print(result)
    """
    if timeout is None:
        timeout = Config.LLM_TIMEOUT

    if "model" in kwargs:
        raise PermissionError("调用方禁止传入 model 参数，模型由项目配置统一指定")

    model = (Config.LITELLM_MODEL or "").strip()
    if not model:
        raise ValueError(
            "Config.LITELLM_MODEL 未配置，请在环境变量 LITELLM_MODEL 中指定默认模型"
        )

    api_key = (Config.DEEPSEEK_API_KEY or "").strip()

    litellm_kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if api_key:
        litellm_kwargs["api_key"] = api_key
    litellm_kwargs.update(kwargs)

    if Config.LLM_LOG_QUERY:
        logger.info(
            f"LLM 请求: model={model}, messages_count={len(messages)}, max_tokens={max_tokens}, timeout={timeout}",
        )

    try:
        # TODO 支持打断请求: 当前通过 Agent.cancel_think() 取消包裹的 asyncio Task
        response = await acompletion(**litellm_kwargs)
    except litellm.exceptions.AuthenticationError as exc:
        raise LLMGateError(
            f"LLM 认证失败: {exc}",
            retryable=False,
        ) from exc
    except litellm.exceptions.BadRequestError as exc:
        raise LLMGateError(
            f"LLM 请求参数错误: {exc}",
            retryable=False,
        ) from exc
    except litellm.exceptions.APIError as exc:
        raise LLMGateError(
            f"LLM API 错误: {exc}",
            retryable=True,
        ) from exc
    except _RETRYABLE_EXCEPTIONS as exc:
        raise LLMGateError(
            f"LLM 调用失败（可重试）: {exc}",
            retryable=True,
        ) from exc
    except litellm.exceptions.UnsupportedParamsError as exc:
        raise LLMGateError(
            f"LLM 不支持的参数: {exc}",
            retryable=False,
        ) from exc
    except Exception as exc:
        raise LLMGateError(
            f"LLM 调用发生未预期错误: {type(exc).__name__}: {exc}",
            retryable=False,
        ) from exc

    content: Any = response.choices[0].message.content

    if Config.LLM_LOG_RESPONSE:
        display = str(content)[: Config.LLM_LOG_MAX_CHARS] if content else "<empty>"
        logger.info(f"LLM 响应: {display}")

    return str(content) if content is not None else ""
