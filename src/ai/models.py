"""models.dev 模型能力与定价查询 —— 唯一信息源。

从 ``https://models.dev/api.json`` 拉取社区维护的模型数据库，
缓存到 ``data/ai/`` 目录（按时间命名，过期自动刷新）。
作为模型定价和能力的第一信息源，替代 litellm 内置数据。

网络不可用或过慢时不阻塞对话：查询只使用当前可用缓存
（内存 → 磁盘 → 过期），刷新在后台单飞进行，失败仅记录日志。

用法::

    from src.ai.models import init_cache, get_pricing_by_id, get_capabilities_by_id

    init_cache(Path("data/ai"))

    pricing = await get_pricing_by_id("openai/gpt-4o-mini")
    caps = await get_capabilities_by_id("deepseek/deepseek-v4-pro")
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003
from typing import Any

from src.utils import get_logger

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
_refresh_task: asyncio.Task[None] | None = None


def init_cache(cache_dir: Path) -> None:
    """设置 models.dev 磁盘缓存目录（需在首次查询前调用）。

    刷新在首次查询或显式调用 refresh_now 时后台调度，不在设置缓存目录时触发。
    """
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
    return _cache_dir / f"{_CACHE_FILE_PREFIX}{timestamp.strftime('%Y%m%d-%H')}.json.gz"


def _read_cache_file(path: Path) -> dict[str, Any] | None:
    try:
        if path.name.endswith(".json.gz"):
            with gzip.open(path, mode="rt", encoding="utf-8") as stream:
                value = json.load(stream)
        elif path.name.endswith(".json"):
            value = json.loads(path.read_text(encoding="utf-8"))
        else:
            return None
    except (gzip.BadGzipFile, json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _find_disk_cache() -> tuple[dict[str, Any] | None, bool]:
    """查找最新的可读磁盘缓存，返回 (data, 是否未过期) 或 (None, False)。"""
    if _cache_dir is None or not _cache_dir.is_dir():
        return None, False
    now = time.time()
    for entry in sorted(_cache_dir.iterdir(), reverse=True):
        if not entry.is_file() or not entry.name.startswith(_CACHE_FILE_PREFIX):
            continue
        if not entry.name.endswith((".json", ".json.gz")):
            continue
        data = _read_cache_file(entry)
        if data is None:
            continue
        return data, (now - entry.stat().st_mtime) < CACHE_TTL_SEC
    return None, False


def _write_cache(data: dict[str, Any]) -> None:
    """写入新缓存文件并清理过期文件。"""
    if _cache_dir is None:
        return
    now = datetime.now(tz=UTC)
    new_path = _cache_file_path(now)
    temporary = new_path.with_suffix(f"{new_path.suffix}.tmp")
    try:
        with gzip.open(temporary, mode="wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
        temporary.replace(new_path)
    except OSError:
        logger.warning("无法写入 models.dev 缓存: %s", new_path)
        temporary.unlink(missing_ok=True)
        return

    for entry in sorted(_cache_dir.iterdir()):
        if not entry.is_file() or entry == new_path or not entry.name.startswith(_CACHE_FILE_PREFIX):
            continue
        if not entry.name.endswith((".json", ".json.gz")):
            continue
        with contextlib.suppress(OSError):
            entry.unlink()


# ═══════════════════════════════════════════════════════════
# 缓存加载与后台刷新
# ═══════════════════════════════════════════════════════════


def _index_models(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """将 models.dev 原始数据索引为 "provider/model_name" → 模型信息。"""
    indexed: dict[str, dict[str, Any]] = {}
    for provider_id, provider_info in raw.items():
        if not isinstance(provider_info, dict):
            continue
        models = provider_info.get("models")
        if not isinstance(models, dict):
            continue
        for model_name, model_info in models.items():
            if isinstance(model_info, dict):
                indexed[f"{provider_id}/{model_name}"] = model_info
    return indexed


async def _load_cache() -> dict[str, dict[str, Any]]:
    """返回当前可用的最优缓存（内存 → 磁盘 → 过期 → 空），不等待网络。

    数据缺失或过期时调度一次后台刷新，调用方立即获得当前可用数据。
    """
    global _cache, _cache_ts
    if _cache is not None:
        if (time.monotonic() - _cache_ts) >= CACHE_TTL_SEC:
            _start_refresh()
        return _cache
    disk_data, disk_fresh = _find_disk_cache()
    if disk_data is not None:
        _cache, _cache_ts = disk_data, time.monotonic()
        if not disk_fresh:
            _start_refresh()
        return _cache
    _start_refresh()
    return {}


async def _refresh_once() -> None:
    """单飞后台刷新：拉取 models.dev 并在成功后更新内存与磁盘缓存。

    有总时限（FETCH_TIMEOUT_SEC），失败只记录日志，绝不抛出。
    """
    global _cache, _cache_ts  # noqa: PLW0603
    async with _lock:
        try:
            raw = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=FETCH_TIMEOUT_SEC)
        except TimeoutError:
            logger.warning("models.dev 数据拉取超时（>%s 秒），继续使用现有缓存", FETCH_TIMEOUT_SEC)
            return
        except urllib.error.URLError as exc:
            logger.warning("models.dev API 不可达: %s", exc)
            return
        except Exception:  # noqa: BLE001
            logger.warning("models.dev 数据拉取失败: %s", _exc_msg())
            return
        if not isinstance(raw, dict) or not raw:
            logger.warning("models.dev 返回数据为空，继续使用现有缓存")
            return

        _cache = _index_models(raw)
        _cache_ts = time.monotonic()
        await asyncio.to_thread(_write_cache, raw)
        logger.debug("models.dev 缓存已更新（%d 个模型）", len(_cache))


def _start_refresh() -> None:
    """若无正在运行的刷新任务，则调度一次后台刷新；无事件循环时不调度。"""
    global _refresh_task  # noqa: PLW0603
    if _refresh_task is not None and not _refresh_task.done():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    _refresh_task = asyncio.create_task(_refresh_once(), name="aurora-modelsdev-refresh")


def _fetch() -> dict[str, Any]:
    """同步拉取 models.dev API 原始数据。"""
    req = urllib.request.Request(
        MODELS_DEV_API,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; AuroraBot/1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
        return json.loads(resp.read())  # type: ignore[no-any-return]


async def refresh_now(wait_seconds: float = FETCH_TIMEOUT_SEC) -> bool:
    """等待一次缓存刷新完成（有超时上限），返回是否有可用数据。

    已有新鲜缓存时立即返回 True。用于冷启动初始化和启动预热。
    """
    if _cache is not None and (time.monotonic() - _cache_ts) < CACHE_TTL_SEC:
        return True
    _start_refresh()
    task = _refresh_task
    if task is None:
        return _cache is not None
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
    except TimeoutError:
        return False
    return _cache is not None


async def cache_available() -> bool:
    """当前是否有可用的 models.dev 数据（内存或磁盘，含过期）。"""
    return bool(await _load_cache())


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
    models = await _load_cache()
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
    models = await _load_cache()
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
    models = await _load_cache()
    return models.get(model_id)
