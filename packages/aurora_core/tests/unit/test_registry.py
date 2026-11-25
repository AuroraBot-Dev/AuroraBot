"""验证定义身份、冲突和分类访问行为。"""

import pytest
from aurora_core.ids import Id
from aurora_core.registry import DefinitionRegistry, RegistryEntry


def entry(path="resources/example", *, kind="resource", target=None):
    return RegistryEntry(Id(f"dev.example:{path}"), kind, target, "测试插件")


@pytest.mark.parametrize(
    "value",
    ["dev.example:resources/a", "org.aurora.core:operations/ctx/get", "dev.test_2:domain_1/a2/b_c"],
)
def test_valid_id(value):
    assert str(Id(value)) == value


@pytest.mark.parametrize(
    "value",
    ["dev:resources/a", "dev.example:r//a", "dev.example:r/../a", "dev.example:R/a", "dev.example:r/a\n"],
)
def test_invalid_id(value):
    with pytest.raises(ValueError):
        Id(value)


def test_non_callable_resource_and_kind_independent_identity():
    registry = DefinitionRegistry()
    resource = entry(target={"content": "提示词"})
    registry.register(resource)
    assert registry.get(resource.id) is resource
    with pytest.raises(ValueError, match="重复"):
        registry.register(entry(kind="operation"))
    assert registry.view(kind="resource") == (resource,)


def test_batch_conflict_is_atomic():
    registry = DefinitionRegistry()
    first = entry()
    registry.register(first)
    with pytest.raises(ValueError):
        registry.register_many((entry("resources/new"), first))
    assert registry.entries() == (first,)


def test_explicit_replace_updates_view():
    registry = DefinitionRegistry()
    original = entry(target="原始资源")
    replacement = entry(target="装配选择")
    with pytest.raises(KeyError):
        registry.replace(replacement)
    registry.register(original)
    registry.replace(replacement)
    assert registry.view(kind="resource") == (replacement,)


def test_short_names_require_unambiguous_context():
    registry = DefinitionRegistry()
    first = entry("commands/a/run", kind="command")
    registry.register(first)
    assert registry.resolve("run", namespace="dev.example", domain="commands") is first
    registry.register(entry("commands/b/run", kind="command"))
    with pytest.raises(ValueError, match="歧义"):
        registry.resolve("run", namespace="dev.example", domain="commands")
    assert registry.resolve("a/run", namespace="dev.example", domain="commands") is first
    with pytest.raises(KeyError):
        registry.resolve("run", namespace="dev.example", domain="resources")
