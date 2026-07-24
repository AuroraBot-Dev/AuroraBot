"""自定义 LLM 供应商配置。

在网关初始化前调用 ``setup_providers()``，将自定义供应商（如硅基流动、
DeepSeek 等 OpenAI 兼容 API）注册到 litellm 配置中。网关在发起 LLM 调用时自动解析
``<provider>/<model>`` 为 litellm 原生模型 ID 并注入 api_base / api_key。

定价与能力以 models.dev 为第一信息源，不再需要 litellm 占位注册。

用法::

    from src.ai.providers import setup_providers

    setup_providers()  # 在网关初始化之前调用一次

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.utils.logging import get_logger

logger = get_logger("Providers")


@dataclass
class ProviderConfig:
    """自定义供应商配置。

    Attributes:
        prefix: 供应商前缀，如 ``"siliconflow"``。
        litellm_provider: LiteLLM 内部使用的 provider，如 ``"openai"``。
        api_base: API 端点地址。
        api_key_env: API Key 所在的环境变量名。
    """

    prefix: str
    litellm_provider: str = "openai"
    api_base: str = ""
    api_key_env: str = ""


# ═══════════════════════════════════════════════════════════
# 内置供应商定义
# ═══════════════════════════════════════════════════════════

SILICONFLOW = ProviderConfig(
    prefix="siliconflow",
    litellm_provider="openai",
    api_base="https://api.siliconflow.cn/v1",
    api_key_env="SILICONFLOW_API_KEY",
)

_registry: dict[str, ProviderConfig] = {}
_setup_signature: tuple[tuple[str, str, str, str], ...] | None = None


# ═══════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════


def setup_providers(*providers: ProviderConfig) -> None:
    """注册自定义供应商。

    在网关初始化之前调用。不传参数则注册所有内置供应商。

    Example::

        from src.ai.providers import setup_providers, SILICONFLOW

        setup_providers(SILICONFLOW)       # 只注册指定供应商
        setup_providers()                  # 注册所有内置供应商
    """
    if not providers:
        providers = (SILICONFLOW,)

    signature = tuple((p.prefix, p.litellm_provider, p.api_base, p.api_key_env) for p in providers)
    expected_prefixes = {p.prefix for p in providers}

    global _setup_signature  # noqa: PLW0603
    if _setup_signature == signature and set(_registry) == expected_prefixes:
        return

    _registry.clear()

    for p in providers:
        if not p.api_base:
            logger.warning("供应商 %s 未配置 api_base，跳过", p.prefix)
            continue
        _registry[p.prefix] = p

    _setup_signature = signature

    logger.info(
        "已注册 %d 个自定义供应商: %s",
        len(_registry),
        ", ".join(_registry.keys()),
    )


def resolve_model(model_id: str) -> tuple[str, dict[str, Any]]:
    """解析模型 ID，返回 ``(litellm_model_id, extra_kwargs)``。

    若 model_id 前缀匹配已注册的供应商，则转换为 litellm 原生模型 ID
    并附加 api_base / api_key；否则原样返回。

    Example::

        model, extra = resolve_model("siliconflow/deepseek-ai/DeepSeek-V3")
        # model  = "openai/deepseek-ai/DeepSeek-V3"
        # extra  = {"api_base": "https://api.siliconflow.cn/v1", "api_key": "sk-xxx"}

        model, extra = resolve_model("openai/gpt-4o-mini")
        # model  = "openai/gpt-4o-mini"
        # extra  = {}
    """
    if "/" not in model_id:
        return model_id, {}

    prefix, _, rest = model_id.partition("/")
    cfg = _registry.get(prefix)

    if cfg is None:
        return model_id, {}

    litellm_model = f"{cfg.litellm_provider}/{rest}"
    extra: dict[str, Any] = {}

    if cfg.api_base:
        extra["api_base"] = cfg.api_base

    api_key = os.getenv(cfg.api_key_env, "")
    if api_key:
        extra["api_key"] = api_key

    logger.debug(
        "模型解析: %s → %s (api_base=%s)",
        model_id,
        litellm_model,
        cfg.api_base,
    )
    return litellm_model, extra


def missing_credentials_reason(model_id: str) -> str | None:
    """检查给定模型是否缺少必要凭证。"""
    if "/" not in model_id:
        return None

    setup_providers()

    prefix, _, _ = model_id.partition("/")
    _, extra = resolve_model(model_id)

    if extra.get("api_key"):
        return None

    if prefix == "openai":
        if os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_ADMIN_KEY"):
            return None
        return f"未配置 OPENAI_API_KEY，无法调用模型 {model_id}"

    cfg = _registry.get(prefix)
    if cfg is None or not cfg.api_key_env:
        return None

    return f"未配置 {cfg.api_key_env}，无法调用模型 {model_id}"
