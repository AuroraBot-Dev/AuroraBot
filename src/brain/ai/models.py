"""models.dev 模型能力与定价查询。

从 ``https://models.dev/api.json`` 拉取社区维护的模型数据库，
提供模型定价与能力查询，作为 litellm 内置定价缺失时的回退数据源。

用法::

    from src.brain.ai.models import get_pricing_by_id

    pricing = await get_pricing_by_id("openai/gpt-4o-mini")
    # => {"input": 0.15, "output": 0.60}  或  None
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from src.utils.log_utils import get_logger

logger = get_logger("ModelsDev")

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

MODELS_DEV_API = "https://models.dev/api.json"
CACHE_TTL_SEC = 3600  # 1 小时
FETCH_TIMEOUT_SEC = 30

# ═══════════════════════════════════════════════════════════
# 模块级缓存
# ═══════════════════════════════════════════════════════════

_cache: dict[str, dict[str, Any]] | None = None
_cache_ts: float = 0.0
_lock = asyncio.Lock()


def _exc_msg() -> str:
    """返回当前异常的简略消息，不打印堆栈。"""
    e = sys.exc_info()[1]
    return f"{type(e).__name__}: {e}" if e is not None else "unknown"


def _is_cache_valid() -> bool:
    """缓存存在且未过期。"""
    return _cache is not None and (time.monotonic() - _cache_ts) < CACHE_TTL_SEC


async def _ensure_cache() -> dict[str, dict[str, Any]]:
    """确保缓存可用，必要时从 models.dev 拉取并索引。

    特性：
    - 首次调用时拉取全量 JSON 并以 ``model_id → model_info`` 建索引
    - 1 小时内重复调用直接命中内存缓存
    - 网络不可达时降级使用过期缓存（如有）
    - 并发安全：双重检查 + asyncio.Lock
    """
    global _cache, _cache_ts

    if _is_cache_valid():
        return _cache  # type: ignore[return-value]

    async with _lock:
        # 双重检查：锁内可能已被上一个竞争者填充
        if _is_cache_valid():
            return _cache  # type: ignore[return-value]

        logger.info("正在从 models.dev 拉取模型数据库...")

        def _fetch() -> dict[str, Any]:
            req = urllib.request.Request(
                MODELS_DEV_API,
                headers={
                    "Accept": "application/json",
                    # Cloudflare 会拦截 Python 默认的 UA，需要伪装
                    "User-Agent": "Mozilla/5.0 (compatible; AuroraBot/1.0)",
                },
            )
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                return json.loads(resp.read())  # type: ignore[no-any-return]

        try:
            data = await asyncio.to_thread(_fetch)
        except urllib.error.URLError as exc:
            logger.warning("models.dev API 不可达: %s", exc)
            if _cache is not None:
                logger.info("降级使用过期缓存（%d 条记录）", len(_cache))
                return _cache
            return {}
        except Exception:
            logger.warning("models.dev 数据拉取/解析失败: %s", _exc_msg())
            if _cache is not None:
                return _cache
            return {}

        # API 结构: { provider_id: { models: { model_name: { id, cost, ... } } } }
        # 构建索引: "provider/model_name" → { input, output, cache_read, ... }
        _cache = {}
        for provider_id, provider_info in data.items():
            if not isinstance(provider_info, dict):
                continue
            models = provider_info.get("models")
            if not isinstance(models, dict):
                continue
            for model_name, model_info in models.items():
                if not isinstance(model_info, dict):
                    continue
                cost = model_info.get("cost")
                if isinstance(cost, dict):
                    _cache[f"{provider_id}/{model_name}"] = cost

        _cache_ts = time.monotonic()
        logger.info("models.dev 缓存已更新（%d 个模型）", len(_cache))
        return _cache


# ═══════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════


async def get_pricing_by_id(model_id: str) -> dict[str, Any] | None:
    """查询指定模型的定价信息。

    数据来源于 ``https://models.dev/api.json``，
    首次调用时拉取全量数据并缓存 1 小时，
    后续调用直接命中内存缓存。

    Args:
        model_id: 模型标识符，格式 ``provider/model_name``，
                  例如 ``"openai/gpt-4o-mini"``、
                  ``"openai/gpt-4o"``。

    Returns:
        定价字典（含 ``input`` / ``output`` 等字段，单位为 USD / 1M tokens），
        模型不存在或数据不可用时返回 ``None``。

    Example::

        from src.brain.ai.models import get_pricing_by_id

        p = await get_pricing_by_id("openai/gpt-4o")
        if p:
            input_cost = p.get("input", 0)    # USD / 1M tokens
            output_cost = p.get("output", 0)  # USD / 1M tokens
    """
    models = await _ensure_cache()
    pricing = models.get(model_id)
    if pricing is None:
        logger.debug("models.dev 中未找到模型: %s", model_id)
        return None
    return pricing
