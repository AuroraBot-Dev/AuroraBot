"""models.dev 模型能力与定价查询 —— 唯一信息源。

从 ``https://models.dev/api.json`` 拉取社区维护的模型数据库，
缓存到 ``data/ai/`` 目录（按时间命名，过期自动刷新）。
作为模型定价和能力的第一信息源，替代 litellm 内置数据。

用法::

    from src.ai.models import init_cache, get_pricing_by_id, get_capabilities_by_id

    init_cache(Path("data/ai"))

    pricing = await get_pricing_by_id("openai/gpt-4o-mini")
    caps = await get_capabilities_by_id("deepseek/deepseek-v4-pro")

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from src.utils.logging import get_logger

logger = get_logger("ModelsDev")

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

MODELS_DEV_API = "https://models.dev/api.json"
CACHE_TTL_SEC = 3600
FETCH_TIMEOUT_SEC = 30
_CACHE_FILE_PREFIX = "models-dev-"

# models.dev 字段 → 内部能力名
_FIELD_CAPABILITY_MAP: dict[str, str] = {
    "tool_call": "tools",
    "reasoning": "reasoning",
    "structured_output": "structured_output",
}

# 无歧义的基础能力
_IMPLICIT_CAPABILITIES: frozenset[str] = frozenset({"chat", "stream", "json_text_fallback"})

# ═══════════════════════════════════════════════════════════
# 模块级状态
# ═══════════════════════════════════════════════════════════

_cache_dir: Path | None = None
_cache: dict[str, dict[str, Any]] | None = None
_cache_ts: float = 0.0
_lock = asyncio.Lock()


def init_cache(cache_dir: Path) -> None:
    """设置 models.dev 磁盘缓存目录（需在首次查询前调用）。"""
    global _cache_dir  # noqa: PLW0603
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_dir = cache_dir


def _exc_msg() -> str:
    e = sys.exc_info()[1]
    return f"{type(e).__name__}: {e}" if e is not None else "unknown"


# ═══════════════════════════════════════════════════════════
# 磁盘缓存
# ═══════════════════════════════════════════════════════════


def _cache_file_path(timestamp: datetime) -> Path:
    assert _cache_dir is not None
    return _cache_dir / f"{_CACHE_FILE_PREFIX}{timestamp.strftime('%Y%m%d-%H')}.json"


def _find_valid_cache() -> tuple[dict[str, Any] | None, float]:
    """查找最新的有效磁盘缓存文件，返回 (data, mtime) 或 (None, 0)。"""
    if _cache_dir is None or not _cache_dir.is_dir():
        return None, 0.0
    now = time.monotonic()
    best: tuple[dict[str, Any], float] | None = None
    for entry in sorted(_cache_dir.iterdir(), reverse=True):
        if not entry.is_file() or not entry.name.startswith(_CACHE_FILE_PREFIX):
            continue
        if not entry.name.endswith(".json"):
            continue
        mtime = entry.stat().st_mtime
        age = now - mtime
        if age >= CACHE_TTL_SEC:
            # 过期文件稍后清理
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            return data, mtime
    return best or (None, 0.0)


def _write_cache(data: dict[str, Any]) -> None:
    """写入新缓存文件并清理过期文件。"""
    if _cache_dir is None:
        return
    now = datetime.now(tz=UTC)
    new_path = _cache_file_path(now)
    try:
        new_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except OSError:
        logger.warning("无法写入 models.dev 缓存: %s", new_path)
        return

    threshold = time.monotonic() - CACHE_TTL_SEC
    for entry in sorted(_cache_dir.iterdir()):
        if not entry.is_file() or entry is new_path or not entry.name.startswith(_CACHE_FILE_PREFIX):
            continue
        if not entry.name.endswith(".json"):
            continue
        try:
            if entry.stat().st_mtime < threshold:
                entry.unlink()
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════
# 缓存保障
# ═══════════════════════════════════════════════════════════


async def _ensure_cache() -> dict[str, dict[str, Any]]:  # noqa: C901
    """确保内存缓存可用。

    优先级：
    1. 有效的内存缓存
    2. 有效的磁盘缓存
    3. 从 models.dev API 拉取 → 写磁盘
    4. 降级到过期缓存（内存或磁盘）
    """
    global _cache, _cache_ts  # noqa: PLW0603

    if _cache is not None and (time.monotonic() - _cache_ts) < CACHE_TTL_SEC:
        return _cache

    async with _lock:
        if _cache is not None and (time.monotonic() - _cache_ts) < CACHE_TTL_SEC:
            return _cache

        # 尝试磁盘缓存
        disk_data, disk_mtime = _find_valid_cache()
        if disk_data is not None:
            _cache, _cache_ts = disk_data, disk_mtime
            logger.debug("从磁盘缓存加载 models.dev（%d 条记录）", len(_cache))
            return _cache

        # 从 API 拉取
        logger.debug("正在从 models.dev 拉取模型数据库...")

        def _fetch() -> dict[str, Any]:
            req = urllib.request.Request(
                MODELS_DEV_API,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (compatible; AuroraBot/1.0)",
                },
            )
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
                return json.loads(resp.read())  # type: ignore[no-any-return]

        try:
            raw = await asyncio.to_thread(_fetch)
        except urllib.error.URLError as exc:
            logger.warning("models.dev API 不可达: %s", exc)
            return _fallback_cache()
        except Exception:  # noqa: BLE001
            logger.warning("models.dev 数据拉取失败: %s", _exc_msg())
            return _fallback_cache()

        # 索引原始数据: "provider/model_name" → full model info dict
        _cache = {}
        for provider_id, provider_info in raw.items():
            if not isinstance(provider_info, dict):
                continue
            models = provider_info.get("models")
            if not isinstance(models, dict):
                continue
            for model_name, model_info in models.items():
                if isinstance(model_info, dict):
                    _cache[f"{provider_id}/{model_name}"] = model_info

        _cache_ts = time.monotonic()

        # 写磁盘缓存
        await asyncio.to_thread(_write_cache, raw)
        logger.debug("models.dev 缓存已更新（%d 个模型）", len(_cache))
        return _cache


def _fallback_cache() -> dict[str, dict[str, Any]]:  # noqa: C901
    """API 不可达时降级：内存缓存 > 过期磁盘文件。"""
    global _cache, _cache_ts  # noqa: PLW0603

    if _cache is not None:
        logger.info("降级使用过期内存缓存（%d 条记录）", len(_cache))
        return _cache

    if _cache_dir is not None:
        for entry in sorted(_cache_dir.iterdir(), reverse=True):
            if not entry.is_file() or not entry.name.startswith(_CACHE_FILE_PREFIX):
                continue
            if not entry.name.endswith(".json"):
                continue
            try:
                raw = json.loads(entry.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(raw, dict):
                _cache = {}
                for provider_id, provider_info in raw.items():
                    if not isinstance(provider_info, dict):
                        continue
                    models = provider_info.get("models")
                    if not isinstance(models, dict):
                        continue
                    for model_name, model_info in models.items():
                        if isinstance(model_info, dict):
                            _cache[f"{provider_id}/{model_name}"] = model_info
                _cache_ts = entry.stat().st_mtime
                logger.info("降级使用过期磁盘缓存（%d 条记录）", len(_cache))
                return _cache

    return {}


# ═══════════════════════════════════════════════════════════
# 公开 API — 定价（主信息源）
# ═══════════════════════════════════════════════════════════


async def get_pricing_by_id(model_id: str) -> dict[str, Any] | None:
    """查询指定模型的定价（USD / 1M tokens）— models.dev 第一信息源。

    Args:
        model_id: 模型标识符，格式 ``provider/model_name``。

    Returns:
        定价字典（含 ``input`` / ``output`` 等字段），不存在时返回 ``None``。
    """
    models = await _ensure_cache()
    info = models.get(model_id)
    if info is None:
        return None
    cost = info.get("cost")
    return cost if isinstance(cost, dict) else None


async def compute_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """根据 models.dev 定价计算单次调用费用。

    这是 cost 计算的第一（也是唯一）信息源；不再使用 litellm 内置定价。

    Args:
        model_id: 模型标识符，格式 ``provider/model_name``。
        prompt_tokens: 提示词 token 数。
        completion_tokens: 完成 token 数。

    Returns:
        费用（USD），不可用时返回 ``0.0``。
    """
    pricing = await get_pricing_by_id(model_id)
    if pricing is None:
        return 0.0
    input_price = pricing.get("input", 0)
    output_price = pricing.get("output", 0)
    return (prompt_tokens / 1_000_000) * input_price + (completion_tokens / 1_000_000) * output_price


# ═══════════════════════════════════════════════════════════
# 公开 API — 能力（主信息源）
# ═══════════════════════════════════════════════════════════


def _derive_capabilities(info: dict[str, Any]) -> frozenset[str]:
    """从 models.dev 原始模型数据派生内部能力集。"""
    caps: set[str] = set(_IMPLICIT_CAPABILITIES)

    for field, capability in _FIELD_CAPABILITY_MAP.items():
        if info.get(field) is True:
            caps.add(capability)

    modalities = info.get("modalities")
    if isinstance(modalities, dict):
        inputs = modalities.get("input")
        if isinstance(inputs, list) and "image" in inputs:
            caps.add("vision")

    return frozenset(caps)


async def get_capabilities_by_id(model_id: str) -> frozenset[str]:
    """从 models.dev 派生模型能力集 — 第一信息源。

    能力映射：
    - ``tool_call`` → ``tools``
    - ``reasoning`` → ``reasoning``
    - ``structured_output`` → ``structured_output``
    - ``modalities.input`` 含 ``image`` → ``vision``
    - 所有模型隐含 ``chat`` / ``stream`` / ``json_text_fallback``

    Args:
        model_id: 模型标识符，格式 ``provider/model_name``。

    Returns:
        能力名 frozenset；数据不可用时退回隐含能力。
    """
    models = await _ensure_cache()
    info = models.get(model_id)
    if info is None:
        logger.debug("models.dev 中未找到模型 %s，使用隐含能力", model_id)
        return _IMPLICIT_CAPABILITIES
    return _derive_capabilities(info)


async def get_model_info(model_id: str) -> dict[str, Any] | None:
    """返回 models.dev 中指定模型的完整原始信息。

    Args:
        model_id: 模型标识符，格式 ``provider/model_name``。

    Returns:
        模型信息字典；不存在时返回 ``None``。
    """
    models = await _ensure_cache()
    return models.get(model_id)
