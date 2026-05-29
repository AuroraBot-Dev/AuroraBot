"""自定义 LLM 供应商配置。

在网关初始化前调用 ``setup_providers()``，将自定义供应商（如硅基流动、
DeepSeek 等 OpenAI 兼容 API）注册到 litellm 配置中。网关在发起 LLM 调用时自动解析
``<provider>/<model>`` 为 litellm 原生模型 ID 并注入 api_base / api_key。

默认情况下所有角色使用 OpenAI 官方模型，只需配置 ``OPENAI_API_KEY`` 即可运行。
如需切换到其他供应商，修改 ``LLM_GATEWAY_*_MODEL`` 环境变量并配置对应的 API Key。

用法::

    from src.brain.ai.providers import setup_providers

    setup_providers()  # 在网关初始化之前调用一次

配置示例（.env）::

    LLM_GATEWAY_FAST_MODEL=siliconflow/deepseek-ai/DeepSeek-V3
    SILICONFLOW_API_KEY=sk-xxx
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict

import litellm

from src.utils.log_utils import get_logger

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

# 所有已注册供应商
_registry: dict[str, ProviderConfig] = {}
_setup_signature: tuple[tuple[str, str, str, str], ...] | None = None


# ═══════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════


def setup_providers(*providers: ProviderConfig) -> None:
    """注册自定义供应商。

    在网关初始化之前调用。不传参数则注册所有内置供应商。

    Example::

        from src.brain.ai.providers import setup_providers, SILICONFLOW

        setup_providers(SILICONFLOW)       # 只注册指定供应商
        setup_providers()                  # 注册所有内置供应商
    """
    if not providers:
        # 注册所有内置供应商
        providers = (SILICONFLOW,)

    signature = tuple(
        (p.prefix, p.litellm_provider, p.api_base, p.api_key_env) for p in providers
    )
    expected_prefixes = {p.prefix for p in providers}

    global _setup_signature
    if _setup_signature == signature and set(_registry) == expected_prefixes:
        return

    _registry.clear()

    for p in providers:
        if not p.api_base:
            logger.warning("供应商 %s 未配置 api_base，跳过", p.prefix)
            continue

        _registry[p.prefix] = p

        # 注册 token 定价占位（实际计费优先使用 models.dev 回退）
        _register_pricing_placeholders(p)

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


# ═══════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════


def _register_pricing_placeholders(provider: ProviderConfig) -> None:
    """为供应商注册常见模型的占位定价。

    litellm 对未知模型的 completion_cost 会抛异常，
    注册占位后至少不会异常中断，实际准确计费依赖 models.dev 回退。
    """
    # 硅基流动通用定价（RMB ¥1.00 / 1M tokens ≈ USD $0.14 / 1M tokens）
    # 仅作占位 — 实际费用由 models.dev 或 litellm 内置定价表提供
    placeholder_input = 0.14 / 1_000_000
    placeholder_output = 0.14 / 1_000_000

    try:
        litellm.register_model(
            {
                f"{provider.prefix}/*": {
                    "litellm_provider": provider.litellm_provider,
                    "mode": "chat",
                    "input_cost_per_token": placeholder_input,
                    "output_cost_per_token": placeholder_output,
                }
            }
        )
    except Exception:
        logger.debug("占位定价注册失败（非关键）: %s", provider.prefix)
