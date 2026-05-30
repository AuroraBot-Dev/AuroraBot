"""providers 自定义供应商模块测试。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.brain.ai import providers as providers_module
from src.brain.ai.providers import (
    SILICONFLOW,
    ProviderConfig,
    _registry,
    resolve_model,
    setup_providers,
)


# ═══════════════════════════════════════════════════════════
# resolve_model — 供应商解析
# ═══════════════════════════════════════════════════════════


class ResolveModelTest(unittest.TestCase):
    def setUp(self) -> None:
        _registry.clear()
        _registry["siliconflow"] = SILICONFLOW

    def tearDown(self) -> None:
        _registry.clear()

    def test_resolves_known_provider(self) -> None:
        """已知供应商 → litellm 原生模型 + extra kwargs。"""
        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": "sk-test"}):
            model, extra = resolve_model("siliconflow/deepseek-ai/DeepSeek-V3")

        self.assertEqual(model, "openai/deepseek-ai/DeepSeek-V3")
        self.assertEqual(extra["api_base"], "https://api.siliconflow.cn/v1")
        self.assertEqual(extra["api_key"], "sk-test")

    def test_resolves_without_api_key(self) -> None:
        """api_key 未设置环境变量时不应出现在 extra 中。"""
        with patch.dict(os.environ, {}, clear=True):
            model, extra = resolve_model("siliconflow/some-model")

        self.assertEqual(model, "openai/some-model")
        self.assertIn("api_base", extra)
        self.assertNotIn("api_key", extra)

    def test_passthrough_standard_model(self) -> None:
        """标准模型（非自定义供应商）原样返回。"""
        model, extra = resolve_model("deepseek/deepseek-chat")
        self.assertEqual(model, "deepseek/deepseek-chat")
        self.assertEqual(extra, {})

    def test_passthrough_unknown_provider(self) -> None:
        """未注册的前缀原样返回。"""
        model, extra = resolve_model("nonexistent/model")
        self.assertEqual(model, "nonexistent/model")
        self.assertEqual(extra, {})

    def test_passthrough_no_slash(self) -> None:
        """不含 / 的模型名原样返回。"""
        model, extra = resolve_model("gpt-4o")
        self.assertEqual(model, "gpt-4o")
        self.assertEqual(extra, {})

    def test_model_with_multiple_slashes(self) -> None:
        """模型名含多个 / （如 siliconflow/deepseek-ai/DeepSeek-V3）。"""
        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": "sk-test"}):
            model, extra = resolve_model("siliconflow/deepseek-ai/DeepSeek-V3")

        # 第一个 / 之前是前缀，之后全部是模型名
        self.assertEqual(model, "openai/deepseek-ai/DeepSeek-V3")


# ═══════════════════════════════════════════════════════════
# setup_providers — 注册
# ═══════════════════════════════════════════════════════════


class SetupProvidersTest(unittest.TestCase):
    def tearDown(self) -> None:
        _registry.clear()

    def test_default_registers_builtin_providers(self) -> None:
        """无参数时注册所有内置供应商。"""
        setup_providers()
        self.assertIn("siliconflow", _registry)

    def test_explicit_providers_overrides_defaults(self) -> None:
        """传入参数时只注册指定的供应商。"""
        custom = ProviderConfig(
            prefix="custom-prefix",
            litellm_provider="openai",
            api_base="https://custom.api/v1",
            api_key_env="CUSTOM_KEY",
        )
        setup_providers(custom)
        self.assertIn("custom-prefix", _registry)
        self.assertNotIn("siliconflow", _registry)

    def test_skips_provider_without_api_base(self) -> None:
        """未配置 api_base 的供应商被跳过。"""
        no_base = ProviderConfig(
            prefix="nobase",
            litellm_provider="openai",
            api_base="",
            api_key_env="NOBASE_KEY",
        )
        setup_providers(no_base)
        self.assertNotIn("nobase", _registry)

    def test_clears_previous_registry(self) -> None:
        """重复调用会清空旧注册。"""
        _registry["stale"] = SILICONFLOW
        setup_providers()
        self.assertIn("siliconflow", _registry)
        # 旧注册被清掉，长度只有内置供应商的数量
        self.assertEqual(len(_registry), 1)


# ═══════════════════════════════════════════════════════════
# ProviderConfig — 数据类
# ═══════════════════════════════════════════════════════════


class ProviderConfigTest(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = ProviderConfig(prefix="test")
        self.assertEqual(cfg.prefix, "test")
        self.assertEqual(cfg.litellm_provider, "openai")
        self.assertEqual(cfg.api_base, "")
        self.assertEqual(cfg.api_key_env, "")

    def test_siliconflow_preset(self) -> None:
        self.assertEqual(SILICONFLOW.prefix, "siliconflow")
        self.assertEqual(SILICONFLOW.api_base, "https://api.siliconflow.cn/v1")
        self.assertEqual(SILICONFLOW.api_key_env, "SILICONFLOW_API_KEY")


if __name__ == "__main__":
    unittest.main()
