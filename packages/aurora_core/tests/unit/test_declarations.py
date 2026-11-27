"""验证装饰声明保持函数语义，并仅在显式装配时登记。"""

import asyncio
import inspect

import pytest
from aurora_core import Id, entry_from, operation, plug
from aurora_core.admission import AdmissionStatus, inspect_admissions
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import Plugin, register_plugins


def test_decorator_preserves_function_and_does_not_register_or_call():
    registry = bootstrap()
    before = registry.entries()
    calls = []

    def original(value: str, *, prefix: str = "") -> str:
        """拼接输入。"""
        calls.append(value)
        return prefix + value

    decorated = operation("dev.example:operations/echo")(original)
    assert decorated is original
    assert registry.entries() == before
    assert calls == []
    entry = entry_from(decorated, provider="example")
    register_plugins(registry, [Plugin("example", (entry,))])
    target = registry.get(entry.id).target
    assert callable(target)
    assert target("内容", prefix="前缀") == "前缀内容"
    assert calls == ["内容"]


def test_async_function_keeps_coroutine_identity():
    @operation(Id("dev.example:operations/async_echo"))
    async def echo(value):
        return value

    assert inspect.iscoroutinefunction(echo)
    assert asyncio.run(echo(42)) == 42


def test_bound_method_keeps_its_instance():
    class Service:
        def __init__(self, value):
            self.value = value

        @operation("dev.example:operations/value")
        def read(self):
            return self.value

    first = entry_from(Service(1).read, provider="example")
    second = entry_from(Service(2).read, provider="example")
    assert first.id == second.id
    assert callable(first.target)
    assert callable(second.target)
    assert first.target() == 1
    assert second.target() == 2
    registry = bootstrap()
    with pytest.raises(ValueError, match="重复"):
        registry.register_many((first, second))


def test_plug_declaration_does_not_choose_a_target_slot():
    @plug("dev.example:handlers/prepare")
    def prepare(value):
        return value

    registry = bootstrap()
    entry = entry_from(prepare, provider="example")
    registry.register(entry)
    assert entry.kind == "hook_handler"
    assert inspect_admissions(registry)[-1].status == AdmissionStatus.ACCEPTED


def test_invalid_and_duplicate_declarations_fail_early():
    with pytest.raises(ValueError, match="无效"):
        operation("invalid")
    with pytest.raises(ValueError, match="无效"):
        plug("invalid")

    @operation("dev.example:operations/test")
    def function():
        pass

    with pytest.raises(ValueError, match="一个公共声明"):
        operation("dev.example:operations/another")(function)
    with pytest.raises(TypeError, match="函数或方法"):
        operation("dev.example:operations/class")(type("Example", (), {}))
    with pytest.raises(TypeError, match="没有有效"):
        entry_from(lambda: None, provider="example")


def test_plug_identity_binds_independent_methods_without_declaring_a_target_slot():
    from aurora_core import plug
    from aurora_core.components import (
        ComponentDeclaration,
        ComponentFactory,
        Definition,
        InstanceExport,
        PluginDeclaration,
    )
    from aurora_core.declarations import plug_id

    identity = Id("dev.example:handlers/read")

    class Service:
        def __init__(self, value):
            self.value = value

        @plug(identity)
        async def read(self):
            return self.value

    assert inspect.iscoroutinefunction(Service.read)
    assert asyncio.run(Service(7).read()) == 7
    assert asyncio.run(Service(8).read()) == 8
    assert plug_id(Service(1).read) == identity
    declaration = PluginDeclaration(
        "example",
        (Definition(identity, "hook_handler", "example"),),
        components={"service": ComponentDeclaration(inject=("value",), plugs=(identity,))},
    )
    factory = ComponentFactory(
        Service, lambda instance: InstanceExport(plugs={identity: instance.read}), (Service.read,)
    )
    plugin = declaration.bind(targets={}, components={"service": factory})
    assert plugin.entries[0].target is Service.read

    first = plugin.components["service"].create({"value": 7}, instance_id="first")
    second = plugin.components["service"].create({"value": 8}, instance_id="second")
    assert asyncio.run(first.exports.plugs[identity]()) == 7
    assert asyncio.run(second.exports.plugs[identity]()) == 8
    incomplete = ComponentFactory(Service, lambda instance: InstanceExport(), (Service.read,))
    incomplete_plugin = declaration.bind(targets={}, components={"service": incomplete})
    with pytest.raises(ValueError, match="导出"):
        incomplete_plugin.components["service"].create({"value": 1}, instance_id="incomplete")
    with pytest.raises(ValueError, match="插头导出"):
        declaration.bind(
            targets={}, components={"service": ComponentFactory(Service, lambda instance: InstanceExport())}
        )
