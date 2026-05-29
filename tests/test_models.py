"""models.dev 模型定价查询模块测试。"""

from __future__ import annotations

import asyncio
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import urllib.error

from src.brain.ai import models as models_module

# ═══════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════

_MOCK_MODELS: list[dict] = [
    {
        "id": "deepseek/deepseek-chat",
        "name": "DeepSeek Chat",
        "provider": "deepseek",
        "pricing": {"input": 0.27, "output": 1.10},
        "contextWindow": 65536,
    },
    {
        "id": "openai/gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "pricing": {"input": 2.50, "output": 10.00},
        "contextWindow": 128000,
    },
    {
        "id": "anthropic/claude-sonnet-4-20250514",
        "name": "Claude Sonnet 4",
        "provider": "anthropic",
        "pricing": {"input": 3.00, "output": 15.00},
        "contextWindow": 200000,
    },
]

_MOCK_JSON_BYTES = json.dumps(_MOCK_MODELS).encode("utf-8")


def _make_mock_urlopen_response(data: bytes = _MOCK_JSON_BYTES) -> MagicMock:
    """构造一个模拟的 urlopen 响应。"""
    mock = MagicMock()
    mock.__enter__.return_value.read.return_value = data
    return mock


def _reset_cache() -> None:
    """重置模块级缓存，避免测试间相互污染。"""
    models_module._cache = None
    models_module._cache_ts = 0.0


# ═══════════════════════════════════════════════════════════
# get_pricing_by_id — 正常路径
# ═══════════════════════════════════════════════════════════


class GetPricingByIdTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def test_returns_pricing_for_known_model(self) -> None:
        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(),
            ):
                pricing = await models_module.get_pricing_by_id(
                    "deepseek/deepseek-chat"
                )
            self.assertIsNotNone(pricing)
            assert pricing is not None
            self.assertEqual(pricing["input"], 0.27)
            self.assertEqual(pricing["output"], 1.10)

        asyncio.run(scenario())

    def test_returns_none_for_unknown_model(self) -> None:
        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(),
            ):
                pricing = await models_module.get_pricing_by_id(
                    "nonexistent/model"
                )
            self.assertIsNone(pricing)

        asyncio.run(scenario())

    def test_second_call_uses_cache(self) -> None:
        """连续两次查询，只应触发一次 HTTP 请求。"""
        async def scenario() -> None:
            mock_urlopen = MagicMock(
                return_value=_make_mock_urlopen_response()
            )
            with patch("urllib.request.urlopen", mock_urlopen):
                p1 = await models_module.get_pricing_by_id("openai/gpt-4o")
                p2 = await models_module.get_pricing_by_id("openai/gpt-4o")
            self.assertEqual(p1, p2)
            self.assertEqual(mock_urlopen.call_count, 1)

        asyncio.run(scenario())

    def test_returns_pricing_for_multiple_models_from_same_fetch(self) -> None:
        """同一次拉取可查询多个模型。"""
        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(),
            ):
                p_deepseek = await models_module.get_pricing_by_id(
                    "deepseek/deepseek-chat"
                )
                p_openai = await models_module.get_pricing_by_id(
                    "openai/gpt-4o"
                )
                p_anthropic = await models_module.get_pricing_by_id(
                    "anthropic/claude-sonnet-4-20250514"
                )
            self.assertIsNotNone(p_deepseek)
            self.assertIsNotNone(p_openai)
            self.assertIsNotNone(p_anthropic)
            assert p_deepseek is not None
            assert p_openai is not None
            self.assertEqual(p_deepseek["input"], 0.27)
            self.assertEqual(p_openai["input"], 2.50)

        asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════
# get_pricing_by_id — 缓存过期
# ═══════════════════════════════════════════════════════════


class CacheExpiryTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def test_re_fetches_after_ttl(self) -> None:
        """缓存过期后应重新拉取。"""
        async def scenario() -> None:
            mock_urlopen = MagicMock(
                return_value=_make_mock_urlopen_response()
            )
            with patch("urllib.request.urlopen", mock_urlopen):
                with patch("time.monotonic", return_value=0.0):
                    await models_module.get_pricing_by_id("openai/gpt-4o")
                # 此时缓存已填充，时间戳为 0
                # 推进时间超过 TTL
                with patch(
                    "time.monotonic",
                    return_value=models_module.CACHE_TTL_SEC + 1,
                ):
                    await models_module.get_pricing_by_id("openai/gpt-4o")
            # 两次：首次拉取 + 过期后重拉
            self.assertEqual(mock_urlopen.call_count, 2)

        asyncio.run(scenario())

    def test_does_not_refetch_within_ttl(self) -> None:
        """缓存未过期时不重新拉取。"""
        async def scenario() -> None:
            mock_urlopen = MagicMock(
                return_value=_make_mock_urlopen_response()
            )
            with patch("urllib.request.urlopen", mock_urlopen):
                with patch("time.monotonic", return_value=100.0):
                    await models_module.get_pricing_by_id("openai/gpt-4o")
                # 仍在 TTL 内
                with patch(
                    "time.monotonic",
                    return_value=100.0 + models_module.CACHE_TTL_SEC - 1,
                ):
                    await models_module.get_pricing_by_id("openai/gpt-4o")
            self.assertEqual(mock_urlopen.call_count, 1)

        asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════
# get_pricing_by_id — 错误降级
# ═══════════════════════════════════════════════════════════


class ErrorDegradationTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def test_returns_none_on_first_fetch_network_error(self) -> None:
        """首次拉取网络不通 → 返回 None。"""
        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("connection refused"),
            ):
                pricing = await models_module.get_pricing_by_id(
                    "deepseek/deepseek-chat"
                )
            self.assertIsNone(pricing)

        asyncio.run(scenario())

    def test_uses_stale_cache_on_refetch_failure(self) -> None:
        """已有缓存时，重新拉取失败则降级使用过期缓存。"""
        async def scenario() -> None:
            # 第一步：成功拉取填充缓存（时间戳 = 0）
            with patch("time.monotonic", return_value=0.0):
                with patch(
                    "urllib.request.urlopen",
                    return_value=_make_mock_urlopen_response(),
                ):
                    await models_module.get_pricing_by_id("openai/gpt-4o")

            # 第二步：过期后拉取失败，应降级使用旧缓存
            with patch(
                "time.monotonic",
                return_value=models_module.CACHE_TTL_SEC + 10,
            ):
                with patch(
                    "urllib.request.urlopen",
                    side_effect=urllib.error.URLError("timeout"),
                ):
                    pricing = await models_module.get_pricing_by_id("openai/gpt-4o")

            self.assertIsNotNone(pricing)
            assert pricing is not None
            self.assertEqual(pricing["input"], 2.50)

        asyncio.run(scenario())

    def test_returns_none_on_json_decode_error_first_fetch(self) -> None:
        """首次拉取返回非法 JSON → 返回 None。"""
        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(b"not valid json"),
            ):
                pricing = await models_module.get_pricing_by_id(
                    "deepseek/deepseek-chat"
                )
            self.assertIsNone(pricing)

        asyncio.run(scenario())

    def test_empty_array_returns_none_for_any_model(self) -> None:
        """API 返回空数组时，任何查询都返回 None。"""
        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(b"[]"),
            ):
                pricing = await models_module.get_pricing_by_id(
                    "deepseek/deepseek-chat"
                )
            self.assertIsNone(pricing)

        asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════
# get_pricing_by_id — 并发安全
# ═══════════════════════════════════════════════════════════


class ConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def test_concurrent_calls_fetch_only_once(self) -> None:
        """多个并发查询只触发一次 HTTP 请求。"""
        async def scenario() -> None:
            # 用一个慢速 mock 让并发窗口足够大
            mock_urlopen = MagicMock(
                return_value=_make_mock_urlopen_response()
            )

            with patch("urllib.request.urlopen", mock_urlopen):
                # 同时发起 5 个查询
                results = await asyncio.gather(
                    models_module.get_pricing_by_id("deepseek/deepseek-chat"),
                    models_module.get_pricing_by_id("openai/gpt-4o"),
                    models_module.get_pricing_by_id("deepseek/deepseek-chat"),
                    models_module.get_pricing_by_id(
                        "anthropic/claude-sonnet-4-20250514"
                    ),
                    models_module.get_pricing_by_id("openai/gpt-4o"),
                )

            # 所有查询都成功
            for r in results:
                self.assertIsNotNone(r)

            # 只拉取了一次
            self.assertEqual(mock_urlopen.call_count, 1)

        asyncio.run(scenario())


# ═══════════════════════════════════════════════════════════
# get_pricing_by_id — 边界情况
# ═══════════════════════════════════════════════════════════


class EdgeCaseTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache()

    def test_model_without_pricing_field_returns_none(self) -> None:
        """模型条目缺少 pricing 字段 → get_pricing_by_id 返回 None。"""
        models_without_pricing = [
            {
                "id": "some/model",
                "name": "No Pricing Model",
                "provider": "some",
            }
        ]

        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(
                    json.dumps(models_without_pricing).encode()
                ),
            ):
                pricing = await models_module.get_pricing_by_id("some/model")
            self.assertIsNone(pricing)

        asyncio.run(scenario())

    def test_model_without_id_field_is_skipped(self) -> None:
        """缺少 id 字段的条目被忽略，不影响其他查询。"""
        models_mixed = [
            {"name": "No ID", "pricing": {"input": 1.0, "output": 2.0}},
            {
                "id": "valid/model",
                "pricing": {"input": 0.5, "output": 1.5},
            },
        ]

        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(
                    json.dumps(models_mixed).encode()
                ),
            ):
                pricing = await models_module.get_pricing_by_id("valid/model")
            self.assertIsNotNone(pricing)
            assert pricing is not None
            self.assertEqual(pricing["input"], 0.5)

        asyncio.run(scenario())

    def test_pricing_with_zero_values(self) -> None:
        """免费模型 pricing 为 0 是合法的。"""
        free_models = [
            {
                "id": "free/model",
                "pricing": {"input": 0.0, "output": 0.0},
            }
        ]

        async def scenario() -> None:
            with patch(
                "urllib.request.urlopen",
                return_value=_make_mock_urlopen_response(
                    json.dumps(free_models).encode()
                ),
            ):
                pricing = await models_module.get_pricing_by_id("free/model")
            self.assertIsNotNone(pricing)
            assert pricing is not None
            self.assertEqual(pricing["input"], 0.0)
            self.assertEqual(pricing["output"], 0.0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
