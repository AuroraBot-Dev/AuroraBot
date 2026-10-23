"""通用内核在无 Bot 的情况下完成注册、调用、冲突裁决与清理。"""

import asyncio
import subprocess
import sys

import pytest

from aurora_kernel import CLOSE, PREPARE, RUN, Context, Host, ModuleSpec, namespace


def test_namespaces_share_context_and_hosts_remain_independent() -> None:
    @namespace("counter")
    def counter(ctx: Context) -> None:
        ctx["counter"]["value"] = 0

    @namespace("writer", requires=("counter",))
    def writer(ctx: Context) -> None:
        ctx["counter"]["value"] = 1

    @writer.callpoint("increment")
    def increment(ctx: Context, amount: int) -> int:
        with ctx.transaction() as staged:
            staged["counter"]["value"] += amount
        return ctx["counter"]["value"]

    first = Host((writer, counter)).build()
    second = Host((counter, writer)).build()
    expected = 3
    assert first.call("writer:increment", 2) == expected
    assert second.ctx["counter"]["value"] == 1
    assert first.ctx.last_change is not None
    assert first.ctx.last_change.source == "writer"


def test_single_callpoint_selection_and_collect_order_are_explicit() -> None:
    @namespace("catalog")
    def catalog(_ctx: Context) -> None:
        pass

    catalog.declare("items", mode="collect")

    @catalog.callpoint("choice")
    def default(_ctx: Context) -> str:
        raise AssertionError("失选调用点不应执行")

    @namespace("extension")
    def extension(_ctx: Context) -> None:
        pass

    @extension.hook("catalog:choice", priority=10)
    def selected(_ctx: Context) -> str:
        return "selected"

    @extension.hook("catalog:items")
    def second(_ctx: Context) -> str:
        return "second"

    @catalog.hook("catalog:items")
    def first(_ctx: Context) -> str:
        return "first"

    host = Host((extension, catalog)).build()
    assert host.call("catalog:choice") == "selected"
    assert host.call("catalog:items") == ("first", "second")


@pytest.mark.parametrize("problem", ["duplicate", "missing", "conflict", "cycle"])
def test_registration_failures_precede_any_initializer(problem: str) -> None:
    touched = []

    @namespace("left", requires=("right",) if problem == "cycle" else ())
    def left(_ctx: Context) -> None:
        touched.append("left")

    @namespace("right", requires=("left",))
    def right(_ctx: Context) -> None:
        touched.append("right")

    @left.callpoint("echo")
    def echo(_ctx: Context) -> None:
        pass

    if problem == "duplicate":
        left.declare("echo")
    elif problem == "missing":
        right.hook("absent:echo")(echo)
    elif problem == "conflict":
        right.hook("left:echo")(echo)
    with pytest.raises(ValueError):
        Host((left, right)).build()
    assert touched == []


def test_async_call_and_shutdown_keep_original_failure_and_release_resources() -> None:
    trace = []

    @namespace("worker")
    def worker(_ctx: Context) -> None:
        trace.append("built")

    @worker.on(PREPARE)
    async def prepare(_ctx: Context):
        trace.append("prepared")

        async def cleanup() -> None:
            trace.append("cleaned")

        return cleanup

    @worker.on(CLOSE)
    async def close(_ctx: Context) -> None:
        trace.append("closed")

    @worker.callpoint("echo")
    async def echo(_ctx: Context, value: str) -> str:
        return value

    @worker.on(RUN)
    async def run(_ctx: Context, _stop: asyncio.Event) -> None:
        raise ValueError("后台失败")

    async def scenario() -> None:
        host = Host((worker,))
        lifecycle = await host.prepare()
        with pytest.raises(TypeError, match="acall"):
            host.call("worker:echo", "你好")
        assert await host.acall("worker:echo", "你好") == "你好"
        await lifecycle.activate(asyncio.Event())
        async with asyncio.timeout(1):
            failure = await lifecycle.next_failure()
        assert failure is not None and failure.module_name == "worker"
        assert isinstance(failure.error, ValueError)
        await lifecycle.close()
        with pytest.raises(RuntimeError, match="已关闭"):
            await host.acall("worker:echo", "你好")

    asyncio.run(scenario())
    assert trace == ["prepared", "built", "closed", "cleaned"]


def test_failed_build_is_not_callable_or_reusable() -> None:
    @namespace("broken")
    def broken(_ctx: Context) -> None:
        raise ValueError("失败")

    @broken.callpoint("echo")
    def echo(_ctx: Context) -> None:
        pass

    host = Host((broken,))
    with pytest.raises(ValueError):
        host.build()
    with pytest.raises(RuntimeError):
        host.call("broken:echo")
    with pytest.raises(RuntimeError):
        host.build()


def test_kernel_imports_and_runs_without_bot_or_cli() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'aurora_bot', 'aurora_cli'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from aurora_kernel import Host, namespace
@namespace('standalone')
def standalone(ctx):
    ctx['standalone']['ready'] = True
assert Host((standalone,)).build().ctx['standalone']['ready']
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_missing_optional_namespaces_are_skipped_transitively_and_self_dependency_fails() -> None:
    host = Host(
        (
            ModuleSpec("first", depends=("absent",), optional=True),
            ModuleSpec("second", depends=("first",), optional=True),
        )
    ).build()
    assert not host.ctx
    with pytest.raises(ValueError, match="自身"):
        Host((ModuleSpec("self", depends=("self",)),))


def test_async_callable_is_rejected_before_any_collect_handler_runs() -> None:
    touched = []

    @namespace("mixed")
    def mixed(ctx: Context) -> None:
        pass

    @mixed.callpoint("collect", mode="collect")
    def synchronous(ctx: Context) -> str:
        touched.append("sync")
        return "sync"

    class AsyncHandler:
        async def __call__(self, ctx: Context) -> str:
            touched.append("async")
            return "async"

    mixed.hook("mixed:collect")(AsyncHandler())
    host = Host((mixed,)).build()
    with pytest.raises(TypeError, match="acall"):
        host.call("mixed:collect")
    assert touched == []
    assert asyncio.run(host.acall("mixed:collect")) == ("sync", "async")


def test_call_routes_are_frozen_with_the_host_declarations() -> None:
    @namespace("choice")
    def choice(ctx: Context) -> None:
        pass

    @choice.callpoint("value")
    def first(ctx: Context) -> str:
        return "first"

    original = Host((choice,)).build()

    @choice.hook("choice:value", priority=10)
    def second(ctx: Context) -> str:
        return "second"

    updated = Host((choice,)).build()
    assert original.call("choice:value") == "first"
    assert updated.call("choice:value") == "second"
    assert original.routes["choice:value"].handlers[0][1].callback is first
    assert updated.routes["choice:value"].handlers[0][1].callback is second
