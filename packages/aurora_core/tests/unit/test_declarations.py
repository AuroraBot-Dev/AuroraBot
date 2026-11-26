"""验证装饰声明保持函数语义，并仅在显式装配时登记。"""

import asyncio
import inspect

import pytest
from aurora_core import Id, entry_from, hook_handler, operation
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


def test_handler_declaration_keeps_optional_slot_unconnected():
    @hook_handler("dev.example:handlers/prepare", slot="org.aurora.agent:react/prepare", interface="双方约定")
    def prepare(value):
        return value

    registry = bootstrap()
    entry = entry_from(prepare, provider="example")
    registry.register(entry)
    assert entry.interface == "双方约定"
    assert entry.kind == "hook_handler"
    results = inspect_admissions(registry)[-2:]
    assert [result.status for result in results] == [AdmissionStatus.ACCEPTED, AdmissionStatus.UNCONNECTED]


def test_invalid_and_duplicate_declarations_fail_early():
    with pytest.raises(ValueError, match="无效"):
        operation("invalid")
    with pytest.raises(ValueError, match="无效"):
        hook_handler("dev.example:handlers/test", slot="invalid")

    @operation("dev.example:operations/test")
    def function():
        pass

    with pytest.raises(ValueError, match="一个公共声明"):
        operation("dev.example:operations/another")(function)
    with pytest.raises(TypeError, match="函数或方法"):
        operation("dev.example:operations/class")(type("Example", (), {}))
    with pytest.raises(TypeError, match="没有有效"):
        entry_from(lambda: None, provider="example")
