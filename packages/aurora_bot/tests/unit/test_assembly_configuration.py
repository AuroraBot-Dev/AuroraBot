"""验证默认装配配置、模型角色引用与凭证解析边界。"""

import asyncio

import pytest
from aurora_adapter.model.config import ADAPTERS, BINDINGS, CONFIG, ModelAdapter, resolve_model
from aurora_adapter.model.plugin import plugin
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_bot.assembly import environment_credential
from aurora_bot.assembly_config import parse_config
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import register_plugins
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

ADAPTER = Id("dev.configuration:adapters/fake")


@pytest.mark.parametrize(
    "change",
    [
        {"instance_id": ""},
        {"max_iterations": True},
        {"tool_timeout": float("inf")},
        {"context_view": {"max_chars": 1023}},
        {"notes": {"owner": "other"}},
        {"archive": {"max_chars": 32001}},
        {"archive": {"database": "foreign"}},
        {"context_view": {"states": ["org.aurora.bot:state/config"]}},
        {
            "tools": [
                {"tool": "dev.test:tools/a", "instance_id": "same"},
                {"tool": "dev.test:tools/b", "instance_id": "same"},
            ]
        },
    ],
)
def test_invalid_bot_configuration_is_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        parse_config({"instance_id": "main", "model_role": "reasoning", **change})


@pytest.mark.parametrize(
    "profile",
    [
        {"adapter": str(ADAPTER)},
        {"adapter": "bad", "model": "m"},
        {"adapter": str(ADAPTER), "model": "m", "api_key": "secret"},
        {"adapter": str(ADAPTER), "model": "m", "credential": ""},
        {"adapter": str(ADAPTER), "model": "m", "provider": " "},
        {"adapter": str(ADAPTER), "model": "m", "provider": 1},
        {"adapter": str(ADAPTER), "model": "m", "capabilities": None},
        {"adapter": str(ADAPTER), "model": "m", "capabilities": {"streaming": True}},
        {"adapter": str(ADAPTER), "model": "m", "capabilities": {"streaming": 1, "tool_calls": False}},
        {"adapter": str(ADAPTER), "model": "m", "capabilities": {"streaming": True, "tool_calls": True, "extra": True}},
    ],
)
def test_model_config_validation_is_atomic(profile):
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    ctx = Context(registry)
    try:
        ctx.set(CONFIG, {"valid": {"adapter": str(ADAPTER), "model": "m"}})
        before = ctx.snapshot()
        with pytest.raises((ValueError, TypeError)):
            ctx.set(CONFIG, {"invalid": profile})
        assert ctx.snapshot() == before
    finally:
        ctx.close()


def test_model_binding_resolves_selected_profile_without_caching_clients():
    registry = bootstrap()
    calls = []

    async def factory(config, *, api_key=None):
        calls.append((config, api_key))
        return FakeModel(lambda _: FakeReply((config.model,)))

    registry.register(RegistryEntry(ADAPTER, "adapter", ModelAdapter("chat", factory), "test", register_to=ADAPTERS))
    profiles = {
        "first": {
            "adapter": str(ADAPTER),
            "model": "one",
            "credential": "KEY",
            "provider": "openai",
            "capabilities": {"streaming": True, "tool_calls": True},
        },
        "second": {"adapter": str(ADAPTER), "model": "two", "base_url": "http://localhost"},
    }
    first = resolve_model(registry, profiles, {"reasoning": "first"}, "reasoning")
    second = resolve_model(registry, profiles, {"reasoning": "second"}, "reasoning")
    assert calls == [] and first.credential == "KEY" and second.credential is None
    assert first.config.provider == "openai" and second.config.provider is None
    assert first.config.capabilities is not None and first.config.capabilities.tool_calls
    assert second.config.capabilities is None

    async def scenario():
        clients = [await first.factory(first.config, api_key="runtime"), await second.factory(second.config)]
        assert clients[0] is not clients[1]
        assert [config.model for config, _ in calls] == ["one", "two"]
        for client in clients:
            await client.aclose()

    asyncio.run(scenario())
    with pytest.raises(ValueError, match="未绑定"):
        resolve_model(registry, profiles, {}, "reasoning")
    with pytest.raises(ValueError, match="不存在"):
        resolve_model(registry, profiles, {"reasoning": "missing"}, "reasoning")
    registry.replace(RegistryEntry(ADAPTER, "resource", factory, "test"))
    with pytest.raises(TypeError, match="工厂"):
        resolve_model(registry, profiles, {"reasoning": "first"}, "reasoning")


def test_empty_or_missing_runtime_credentials_fail_explicitly(monkeypatch):
    monkeypatch.delenv("AURORA_TEST_CREDENTIAL", raising=False)
    with pytest.raises(ValueError, match="未提供"):
        environment_credential("AURORA_TEST_CREDENTIAL")
    monkeypatch.setenv("AURORA_TEST_CREDENTIAL", "value")
    assert environment_credential("AURORA_TEST_CREDENTIAL") == "value"


def test_bindings_reject_non_string_targets():
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    ctx = Context(registry)
    try:
        with pytest.raises(ValueError):
            ctx.set(BINDINGS, {"reasoning": 1})
        assert ctx.list() == ()
    finally:
        ctx.close()
