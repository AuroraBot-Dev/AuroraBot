"""gateway 网关模块测试。"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import litellm.exceptions

from src.brain.ai.gateway import (
    ROLE_FAST,
    ROLE_MULTIMODAL,
    ROLE_QUALITY,
    CancelledWithPartialResponse,
    GatewayError,
    ModelGateway,
)

_MESSAGES: list[dict[str, str]] = [
    {"role": "system", "content": "你是一个助手。"},
    {"role": "user", "content": "你好"},
]

_FAST_MODEL = "openai/gpt-4o-mini"
_QUALITY_MODEL = "openai/gpt-4o"
_MULTIMODAL_MODEL = "openai/gpt-4o"
_EMBEDDING_MODEL = "openai/text-embedding-3-small"
_RERANKER_MODEL = ""


# ── helpers ──────────────────────────────────────────────────


def _make_mock_response(content: str | None) -> MagicMock:
    response = MagicMock()
    choice = MagicMock()
    message = MagicMock()
    message.content = content
    choice.message = message
    response.choices = [choice]
    return response


def _make_gateway() -> ModelGateway:
    return ModelGateway(
        fast=_FAST_MODEL,
        quality=_QUALITY_MODEL,
        multimodal=_MULTIMODAL_MODEL,
        embedding=_EMBEDDING_MODEL,
        reranker=_RERANKER_MODEL,
    )


# ── GatewayError ──────────────────────────────────────────────


class GatewayErrorAttributesTest(unittest.TestCase):
    def test_retryable_defaults_to_false(self) -> None:
        error = GatewayError("test")
        self.assertFalse(error.retryable)

    def test_retryable_explicit_true(self) -> None:
        error = GatewayError("test", retryable=True)
        self.assertTrue(error.retryable)

    def test_message_preserved(self) -> None:
        error = GatewayError("something went wrong", retryable=True)
        self.assertEqual(str(error), "something went wrong")


# ── CancelledWithPartialResponse ──────────────────────────────


class CancelledWithPartialResponseTest(unittest.TestCase):
    def test_is_cancelled_error_subclass(self) -> None:
        exc = CancelledWithPartialResponse(None, 0.0)
        self.assertIsInstance(exc, asyncio.CancelledError)

    def test_stores_partial_response_and_cost(self) -> None:
        partial = MagicMock()
        exc = CancelledWithPartialResponse(partial, 0.0123)
        self.assertIs(exc.partial_response, partial)
        self.assertEqual(exc.cost, 0.0123)


# ── ModelGateway ─────────────────────────────────────────────


class ModelGatewayInitTest(unittest.TestCase):
    def test_invalid_model_format_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            ModelGateway(
                fast="gpt4o-mini",
                quality=_QUALITY_MODEL,
                multimodal=_MULTIMODAL_MODEL,
            )
        self.assertIn("provider/model_name", str(ctx.exception))

    def test_all_roles_present(self) -> None:
        gw = _make_gateway()
        self.assertIsNotNone(gw.fast)
        self.assertIsNotNone(gw.quality)
        self.assertIsNotNone(gw.multimodal)

    def test_fast_model_matches_init(self) -> None:
        gw = _make_gateway()
        self.assertEqual(gw.fast.model, _FAST_MODEL)

    def test_quality_model_matches_init(self) -> None:
        gw = _make_gateway()
        self.assertEqual(gw.quality.model, _QUALITY_MODEL)

    def test_export_config_returns_models(self) -> None:
        gw = _make_gateway()
        config = gw.export_config()
        self.assertEqual(config[ROLE_FAST], _FAST_MODEL)
        self.assertEqual(config[ROLE_QUALITY], _QUALITY_MODEL)
        self.assertEqual(config[ROLE_MULTIMODAL], _MULTIMODAL_MODEL)
        self.assertEqual(config["embedding"], _EMBEDDING_MODEL)
        self.assertNotIn("reranker", config)

    def test_embedding_config_is_plain_string(self) -> None:
        gw = _make_gateway()
        self.assertEqual(gw.embedding, _EMBEDDING_MODEL)
        self.assertIsInstance(gw.embedding, str)

    def test_reranker_config_is_plain_string(self) -> None:
        gw = _make_gateway()
        self.assertEqual(gw.reranker, "")
        self.assertIsInstance(gw.reranker, str)

    def test_embedding_and_reranker_default_to_empty(self) -> None:
        gw = ModelGateway(
            fast=_FAST_MODEL,
            quality=_QUALITY_MODEL,
            multimodal=_MULTIMODAL_MODEL,
        )
        self.assertEqual(gw.embedding, "")
        self.assertEqual(gw.reranker, "")


class ModelGatewayUseModelTest(unittest.TestCase):
    def test_valid_roles(self) -> None:
        gw = _make_gateway()
        for role in (ROLE_FAST, ROLE_QUALITY, ROLE_MULTIMODAL):
            gw.use_model(role)

    def test_unknown_role_raises(self) -> None:
        gw = _make_gateway()
        with self.assertRaises(ValueError) as ctx:
            gw.use_model("nonexistent")
        self.assertIn("Unknown role", str(ctx.exception))

    def test_use_model_case_insensitive(self) -> None:
        gw = _make_gateway()
        caller = gw.use_model("FAST")
        self.assertEqual(caller.model, _FAST_MODEL)


# ── plain() static method ─────────────────────────────────────


class ModelGatewayPlainTest(unittest.TestCase):
    def test_plain_returns_content(self) -> None:
        gw = _make_gateway()
        resp = _make_mock_response("Hello, Aurora!")
        self.assertEqual(gw.plain(resp), "Hello, Aurora!")

    def test_plain_returns_empty_for_none(self) -> None:
        gw = _make_gateway()
        self.assertEqual(gw.plain(None), "")

    def test_plain_returns_empty_when_content_is_none(self) -> None:
        gw = _make_gateway()
        resp = _make_mock_response(None)
        self.assertEqual(gw.plain(resp), "")


# ── ModelCaller acompletion ──────────────────────────────────


class ModelCallerAcompletionTest(unittest.TestCase):
    def test_model_in_kwargs_raises_permission_error(self) -> None:
        gw = _make_gateway()
        with self.assertRaises(PermissionError) as ctx:
            gw.fast.acompletion(_MESSAGES, model="some-other-model")
        self.assertIn("model", str(ctx.exception).lower())


# ── Exception conversion ─────────────────────────────────────


class GatewayExceptionConversionTest(unittest.TestCase):
    """验证网关内部将 litellm 异常正确转换为 GatewayError。

    使用 mock 直接测试 ModelCaller.acompletion 的异常传播路径。
    """

    _MOCK_CHUNK = MagicMock()
    _MOCK_CHUNK.usage = MagicMock()
    _MOCK_CHUNK.usage.prompt_tokens = 10
    _MOCK_CHUNK.usage.completion_tokens = 5

    def _make_stream(self, exc: Exception) -> AsyncMock:  # noqa: ARG002
        """创建 mock 流：初始请求成功，但迭代 chunk 时抛出异常。"""
        mock_stream = AsyncMock()
        mock_stream.__aiter__.return_value = [self._MOCK_CHUNK]
        return mock_stream

    def _assert_raises_gateway_error(
        self,
        exc_to_raise: Exception,
        *,
        expected_retryable: bool,
    ) -> None:
        gw = _make_gateway()

        async def scenario() -> None:
            with (
                patch(
                    "src.brain.ai.gateway.missing_credentials_reason",
                    return_value=None,
                ),
                patch(
                    "litellm.acompletion",
                    new=AsyncMock(side_effect=exc_to_raise),
                ),
            ):
                gen = gw.fast.acompletion(_MESSAGES)
                with self.assertRaises(GatewayError) as ctx:
                    await gen
            self.assertEqual(
                ctx.exception.retryable,
                expected_retryable,
                f"retryable 应为 {expected_retryable}，实际 {ctx.exception.retryable}",
            )

        asyncio.run(scenario())

    def test_timeout_is_retryable(self) -> None:
        exc = litellm.exceptions.Timeout(
            message="Request timed out",
            model="mock-model",
            llm_provider="mock-provider",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=True)

    def test_rate_limit_is_retryable(self) -> None:
        exc = litellm.exceptions.RateLimitError(
            message="Rate limit exceeded",
            model="mock-model",
            llm_provider="mock-provider",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=True)

    def test_api_connection_error_is_retryable(self) -> None:
        exc = litellm.exceptions.APIConnectionError(
            message="Connection failed",
            llm_provider="mock-provider",
            model="mock-model",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=True)

    def test_service_unavailable_is_retryable(self) -> None:
        exc = litellm.exceptions.ServiceUnavailableError(
            message="Service unavailable",
            llm_provider="mock-provider",
            model="mock-model",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=True)

    def test_internal_server_error_is_retryable(self) -> None:
        exc = litellm.exceptions.InternalServerError(
            message="Internal error",
            llm_provider="mock-provider",
            model="mock-model",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=True)

    def test_api_error_is_retryable(self) -> None:
        exc = litellm.exceptions.APIError(
            status_code=500,
            message="Generic API error",
            llm_provider="mock-provider",
            model="mock-model",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=True)

    def test_authentication_error_is_not_retryable(self) -> None:
        exc = litellm.exceptions.AuthenticationError(
            message="Invalid API key",
            llm_provider="mock-provider",
            model="mock-model",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=False)

    def test_bad_request_error_is_not_retryable(self) -> None:
        exc = litellm.exceptions.BadRequestError(
            message="Bad request",
            model="mock-model",
            llm_provider="mock-provider",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=False)

    def test_unsupported_params_error_is_not_retryable(self) -> None:
        exc = litellm.exceptions.UnsupportedParamsError(
            message="Unsupported param",
            llm_provider="mock-provider",
            model="mock-model",
        )
        self._assert_raises_gateway_error(exc, expected_retryable=False)

    def test_unexpected_exception_is_not_retryable(self) -> None:
        self._assert_raises_gateway_error(
            RuntimeError("some unexpected crash"),
            expected_retryable=False,
        )

    def test_exception_chaining_preserves_cause(self) -> None:
        gw = _make_gateway()
        original = litellm.exceptions.Timeout(
            message="timed out",
            model="mock-model",
            llm_provider="mock-provider",
        )

        async def scenario() -> None:
            with (
                patch(
                    "src.brain.ai.gateway.missing_credentials_reason",
                    return_value=None,
                ),
                patch(
                    "litellm.acompletion",
                    new=AsyncMock(side_effect=original),
                ),
            ):
                gen = gw.fast.acompletion(_MESSAGES)
                with self.assertRaises(GatewayError) as ctx:
                    await gen
            self.assertIs(ctx.exception.__cause__, original)

        asyncio.run(scenario())

    def test_missing_credentials_fails_fast_without_calling_litellm(self) -> None:
        gw = _make_gateway()

        async def scenario() -> None:
            with (
                patch(
                    "src.brain.ai.gateway.missing_credentials_reason",
                    return_value="未配置 OPENAI_API_KEY，无法调用模型 openai/gpt-4o-mini",
                ),
                patch("litellm.acompletion", new=AsyncMock()) as mock_completion,
            ):
                gen = gw.fast.acompletion(_MESSAGES)
                with self.assertRaises(GatewayError) as ctx:
                    await gen

            self.assertFalse(ctx.exception.retryable)
            self.assertIn("未配置 OPENAI_API_KEY", str(ctx.exception))
            mock_completion.assert_not_awaited()

        asyncio.run(scenario())


# ── CostTracker ────────────────────────────────────────────────


class CostTrackerTest(unittest.TestCase):
    def test_summary_aggregates_by_role_and_model(self) -> None:
        from src.brain.ai.gateway import CostTracker

        tracker = CostTracker()

        async def scenario() -> None:
            await tracker.add({"role": "fast", "model": "m1", "type": "completion", "cost": 0.01})
            await tracker.add({"role": "fast", "model": "m1", "type": "completion", "cost": 0.02})
            await tracker.add({"role": "quality", "model": "m2", "type": "completion", "cost": 0.10})

        asyncio.run(scenario())

        s = asyncio.run(tracker.summary())
        self.assertAlmostEqual(s["total_cost"], 0.13)
        self.assertEqual(s["by_role"]["fast"]["count"], 2)
        self.assertEqual(s["by_role"]["quality"]["count"], 1)
        self.assertAlmostEqual(s["by_role"]["fast"]["cost"], 0.03)


# ── TaskManager ────────────────────────────────────────────────


class TaskManagerTest(unittest.TestCase):
    def test_create_task_returns_generation_task(self) -> None:
        from src.brain.ai.gateway import TaskManager

        async def scenario() -> None:
            tm = TaskManager()

            async def coro() -> tuple[str, float]:
                return "done", 0.0

            gen = tm.create_task(coro())
            self.assertIsNotNone(gen.task_id)
            self.assertEqual(len(gen.task_id), 8)
            # 等待任务完成以清理回调
            await gen

        asyncio.run(scenario())

    def test_abort_nonexistent_returns_false(self) -> None:
        from src.brain.ai.gateway import TaskManager

        async def scenario() -> None:
            tm = TaskManager()
            self.assertFalse(tm.abort("nonexistent"))

        asyncio.run(scenario())


# ── GenerationTask ─────────────────────────────────────────────


class GenerationTaskTest(unittest.TestCase):
    def test_plain_returns_content(self) -> None:
        from src.brain.ai.gateway import TaskManager

        async def scenario() -> None:
            tm = TaskManager()

            async def coro() -> tuple[MagicMock, float]:
                return _make_mock_response("result text"), 0.005

            gen = tm.create_task(coro())
            resp = await gen
            self.assertEqual(resp.choices[0].message.content, "result text")
            self.assertEqual(gen.plain(), "result text")
            self.assertAlmostEqual(gen.cost, 0.005)

        asyncio.run(scenario())

    def test_plain_returns_empty_before_await(self) -> None:
        from src.brain.ai.gateway import TaskManager

        async def scenario() -> None:
            tm = TaskManager()

            async def coro() -> tuple[MagicMock, float]:
                return _make_mock_response("later"), 0.0

            gen = tm.create_task(coro())
            # GenerationTask.response 尚未赋值，plain() 返回 ""
            self.assertEqual(gen.plain(), "")
            # 等待完成避免 coroutine-was-never-awaited 警告
            await gen

        asyncio.run(scenario())

    def test_done_returns_true_after_completion(self) -> None:
        from src.brain.ai.gateway import TaskManager

        async def scenario() -> None:
            tm = TaskManager()

            async def coro() -> tuple[str, float]:
                return "ok", 0.0

            gen = tm.create_task(coro())
            self.assertFalse(gen.done())
            await gen
            self.assertTrue(gen.done())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
