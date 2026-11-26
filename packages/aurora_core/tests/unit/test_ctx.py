"""验证共享状态访问与变化通知的可观察语义。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import StateKey, install_context
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

CONFIG = Id("dev.example:state/config")
OTHER = Id("dev.other:state/data")


@pytest.fixture
def state():
    registry = bootstrap()
    for key in (CONFIG, OTHER):
        registry.register(RegistryEntry(key, "state_key", StateKey(), "测试插件"))
    ctx = install_context(registry)
    yield registry, ctx
    ctx.close()


def test_replacement_and_copy_boundaries(state):
    _, ctx = state
    source = {"items": [1], "old": True}
    ctx.set(CONFIG, source)
    source["items"].append(2)
    value = ctx.get(CONFIG)
    value["items"].append(3)
    assert ctx.get(CONFIG) == {"items": [1], "old": True}
    ctx.set(CONFIG, {"new": True})
    assert ctx.get(CONFIG) == {"new": True}


def test_missing_and_null_are_distinct(state):
    _, ctx = state
    with pytest.raises(KeyError):
        ctx.get(CONFIG)
    assert ctx.delete(CONFIG) is False
    ctx.set(CONFIG, None)
    assert ctx.get(CONFIG) is None
    assert ctx.delete(CONFIG) is True
    assert ctx.delete(CONFIG) is False


def test_addresses_are_exact_canonical_and_shared(state):
    _, ctx = state
    ctx.set(CONFIG, "全局")
    ctx.set(CONFIG, "运行", location={"session_id": "s1", "run_id": "r1"})
    ctx.set(OTHER, "其他命名空间")
    assert ctx.get(CONFIG, location={"run_id": "r1", "session_id": "s1"}) == "运行"
    with pytest.raises(KeyError):
        ctx.get(CONFIG, location={"session_id": "s1"})
    assert [address.key for address in ctx.list()] == [CONFIG, CONFIG, OTHER]
    assert len(ctx.list(key=CONFIG, location={})) == 1
    assert ctx.get(OTHER) == "其他命名空间"


def test_unknown_or_wrong_definition_is_rejected(state):
    registry, ctx = state
    with pytest.raises(KeyError):
        ctx.set(Id("dev.example:state/missing"), 1)
    registry.replace(RegistryEntry(CONFIG, "resource", StateKey(), "测试插件"))
    with pytest.raises(TypeError, match="状态定义"):
        ctx.set(CONFIG, 1)


def test_validation_cannot_change_committed_value_or_retain_reference(state):
    registry, ctx = state
    captured = []

    def validate(value):
        captured.append(value)
        value.append("校验器修改")

    registry.replace(RegistryEntry(CONFIG, "state_key", StateKey(validate), "测试插件"))
    ctx.set(CONFIG, [1])
    captured[0].append(2)
    assert ctx.get(CONFIG) == [1]


def test_validation_failure_is_atomic_and_reentrant_write_rejected(state):
    registry, ctx = state
    received = []
    ctx.subscribe(received.append)
    ctx.set(CONFIG, "初始")

    def validate(value):
        ctx.set(OTHER, "校验内写入")

    registry.replace(RegistryEntry(CONFIG, "state_key", StateKey(validate), "测试插件"))
    with pytest.raises(RuntimeError, match="校验期间"):
        ctx.set(CONFIG, "拒绝")
    assert ctx.get(CONFIG) == "初始"
    assert len(ctx.list()) == 1
    assert len(received) == 1


def test_notifications_include_revision_and_success_only(state):
    _, ctx = state
    received = []
    ctx.subscribe(received.append)
    ctx.set(CONFIG, None)
    ctx.set(CONFIG, None)
    ctx.delete(CONFIG)
    ctx.delete(CONFIG)
    assert [change.revision for change in received] == [1, 2, 3]
    assert [change.action for change in received] == ["set", "set", "delete"]
    assert [change.existed for change in received] == [False, True, True]


def test_subscription_filters_copies_errors_and_cancellation(state, caplog):
    _, ctx = state
    received = []

    def broken(change):
        change.value.append(2)
        raise ValueError("订阅失败")

    ctx.subscribe(broken, key=CONFIG)
    handle = ctx.subscribe(received.append, key=CONFIG, location={"session_id": "s1"})
    ctx.set(OTHER, "其他")
    ctx.set(CONFIG, [1], location={"session_id": "s1"})
    assert ctx.get(CONFIG, location={"session_id": "s1"}) == [1]
    assert received[0].value == [1]
    assert "订阅失败" in caplog.text
    assert ctx.unsubscribe(handle) is True
    assert ctx.unsubscribe(handle) is False
    ctx.set(CONFIG, [3], location={"session_id": "s1"})
    assert len(received) == 1


def test_reentrant_writes_preserve_notification_order(state):
    _, ctx = state
    received = []

    def update(change):
        if change.value == 1:
            ctx.set(CONFIG, 2)

    ctx.subscribe(update)
    ctx.subscribe(received.append)
    ctx.set(CONFIG, 1)
    assert [change.value for change in received] == [1, 2]
    assert [change.revision for change in received] == [1, 2]
    assert ctx.get(CONFIG) == 2


def test_close_releases_subscriptions_and_rejects_access(state):
    _, ctx = state
    handle = ctx.subscribe(lambda change: None)
    ctx.close()
    assert ctx.unsubscribe(handle) is False
    with pytest.raises(RuntimeError, match="关闭"):
        ctx.get(CONFIG)


def test_operations_are_bound_to_this_context(state):
    registry, ctx = state
    registry.get(Id("org.aurora.core:operations/ctx/set")).target(CONFIG, "通过 ID 写入")
    assert ctx.get(CONFIG) == "通过 ID 写入"
    before = registry.entries()
    with pytest.raises(ValueError, match="重复"):
        install_context(registry)
    assert registry.entries() == before


def test_cross_thread_write_is_rejected(state):
    _, ctx = state
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RuntimeError, match="宿主线程"):
        pool.submit(ctx.set, CONFIG, 1).result()
    assert ctx.list() == ()


def test_copy_failure_does_not_commit_or_notify(state):
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise TypeError("不可复制")

    _, ctx = state
    received = []
    ctx.subscribe(received.append)
    with pytest.raises(TypeError, match="不可复制"):
        ctx.set(CONFIG, Uncopyable())
    assert ctx.list() == ()
    assert received == []


def test_coroutine_writes_follow_host_call_order(state):
    _, ctx = state
    received = []
    ctx.subscribe(received.append)

    async def write(value):
        ctx.set(CONFIG, value)

    async def run():
        await asyncio.gather(write(1), write(2), write(3))

    asyncio.run(run())
    assert [change.revision for change in received] == [1, 2, 3]
    assert ctx.get(CONFIG) == 3


@pytest.mark.parametrize("location", [{"session_id": ""}, {"": "s1"}, {"session_id": 1}])
def test_invalid_location_is_rejected_without_write(state, location):
    _, ctx = state
    with pytest.raises(ValueError, match="非空字符串"):
        ctx.set(CONFIG, 1, location=location)
    assert ctx.list() == ()
