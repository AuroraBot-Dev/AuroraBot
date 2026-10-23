from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from playground.protocol import Empty, Model, Operation
from playground.workspace import Archive, InvocationError, Workspace, WorkspaceSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


class Configuration(Model):
    initial: int = 0


class Number(Model):
    value: int


class Increment(Model):
    amount: int = 1


def snapshot(counter: dict[str, int]) -> Number:
    return Number(value=counter["value"])


def increment(counter: dict[str, int], *, amount: int = 1) -> Number:
    counter["value"] += amount
    return snapshot(counter)


def declaration(events: list[str]) -> WorkspaceSpec:
    @contextmanager
    def open_instance(configuration: Model, instance_id: str) -> Iterator[dict[str, int]]:
        parsed = Configuration.model_validate(configuration)
        if parsed.initial < 0:
            raise ValueError("装配被拒绝")
        events.append(f"open:{instance_id}")
        try:
            yield {"value": parsed.initial}
        finally:
            events.append(f"close:{instance_id}")

    return WorkspaceSpec(
        Configuration,
        open_instance,
        Operation("state", "读取值", Empty, Number, snapshot, {}, record=False),
        (Operation("increment", "递增", Increment, Number, increment, {}, replayable=True),),
        isolated=True,
    )


def test_instances_share_management_not_domain_operations() -> None:
    async def exercise() -> None:
        events: list[str] = []
        workspace = Workspace("counter", declaration(events))
        await workspace.create({"initial": 3}, "one")
        await workspace.create({}, "two")
        result = await workspace.call("one", "increment", {"amount": 4})
        assert result == Number(value=3 + 4)
        assert await workspace.snapshot("two") == Number(value=0)
        record = await workspace.export("one")
        assert [item.operation for item in record.checkpoints] == ["increment"]
        assert record.checkpoints[0].output == {"value": 3 + 4}
        assert (await workspace.replay(Archive.model_validate_json(record.model_dump_json()))).matched
        await workspace.reset("one")
        assert await workspace.snapshot("one") == Number(value=3)
        assert (await workspace.export("one")).checkpoints == []
        assert record.checkpoints
        await workspace.close()
        assert events == [
            "open:one",
            "open:two",
            "open:replay",
            "open:one",
            "close:one",
            "close:replay",
            "close:two",
            "close:one",
        ]
        await workspace.close()
        with pytest.raises(RuntimeError, match="关闭"):
            await workspace.create({})

    asyncio.run(exercise())


def test_validation_and_replay_permission_precede_any_assembly_effect() -> None:
    async def exercise() -> None:
        events: list[str] = []
        spec = declaration(events)
        source = Workspace("counter", spec)
        with pytest.raises(ValidationError):
            await source.create({"initial": True})
        assert not events
        await source.create({})
        await source.call("default", "increment")
        record = await source.export()
        target_events: list[str] = []
        target_spec = declaration(target_events)
        for changed in (
            replace(target_spec, isolated=False),
            replace(target_spec, operations=(replace(target_spec.operations[0], replayable=False),)),
        ):
            with pytest.raises(ValueError, match=r"禁止|不允许"):
                await Workspace("counter", changed).replay(record)
        target = Workspace("counter", target_spec)
        invalid = record.model_copy(deep=True)
        invalid.checkpoints[-1].input = {"amount": True}
        with pytest.raises(ValidationError):
            await target.replay(invalid)
        with pytest.raises(ValueError, match="模块或版本"):
            await Workspace("other", target_spec).replay(record)
        with pytest.raises(ValueError, match="模块或版本"):
            await Workspace("counter", replace(target_spec, revision="2")).replay(record)
        assert not target_events
        assert (await target.replay(record)).matched
        await source.close()
        await target.close()

    asyncio.run(exercise())


def test_reset_failure_keeps_previous_instance_and_creation_failure_releases_resources() -> None:
    async def exercise() -> None:
        events: list[str] = []
        spec = declaration(events)
        workspace = Workspace("counter", spec)
        await workspace.create({})
        await workspace.call("default", "increment")
        with pytest.raises(ValueError, match="装配被拒绝"):
            await workspace.reset(configuration={"initial": -1})
        assert await workspace.snapshot() == Number(value=1)

        def broken_snapshot(_counter: dict[str, int]) -> Number:
            raise RuntimeError("快照失败")

        broken = Workspace("broken", replace(spec, snapshot=replace(spec.snapshot, handler=broken_snapshot)))
        with pytest.raises(RuntimeError, match="快照失败"):
            await broken.create({}, "failed")
        assert not broken.active
        assert events[-2:] == ["open:failed", "close:failed"]
        await workspace.close()

    asyncio.run(exercise())


def test_failed_operation_is_redacted_and_replayed_without_losing_checkpoints() -> None:
    async def exercise() -> None:
        events: list[str] = []
        spec = declaration(events)

        def fail(_counter: dict[str, int]) -> Empty:
            raise OSError("包含凭据的异常正文")

        operation = Operation("fail", "失败", Empty, Empty, fail, {}, replayable=True)
        workspace = Workspace("counter", replace(spec, operations=(*spec.operations, operation)))
        await workspace.create({})
        with pytest.raises(InvocationError) as caught:
            await workspace.call("default", "fail")
        assert "包含凭据" not in str(caught.value)
        record = await workspace.export()
        assert record.checkpoints[0].error_type == "OSError"
        assert (await workspace.replay(record)).matched
        record.checkpoints[0].state["value"] = -1
        result = await workspace.replay(record, "different")
        assert not result.matched
        assert result.differences == ["checkpoints[0]"]
        await workspace.close()

    asyncio.run(exercise())


def test_async_resources_reject_concurrent_replacement_and_all_close_after_cleanup_failure() -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        events: list[str] = []
        spec = declaration(events)

        @asynccontextmanager
        async def open_instance(_configuration: Model, instance_id: str) -> AsyncIterator[dict[str, int]]:
            try:
                yield {"value": 0}
            finally:
                events.append(instance_id)
                if instance_id == "broken":
                    raise RuntimeError("释放失败")

        async def wait(counter: dict[str, int]) -> Number:
            entered.set()
            await release.wait()
            return snapshot(counter)

        operation = Operation("wait", "等待", Empty, Number, wait, {})
        workspace = Workspace("counter", replace(spec, open=open_instance, operations=(operation,)))
        await workspace.create({}, "old")
        await workspace.create({}, "broken")
        driver = asyncio.create_task(workspace.call("old", "wait"))
        await entered.wait()
        with pytest.raises(RuntimeError, match="并发"):
            await workspace.reset("old")
        with pytest.raises(RuntimeError, match="执行中"):
            await workspace.close()
        release.set()
        await driver
        with pytest.raises(RuntimeError, match="释放失败"):
            await workspace.close()
        assert events == ["broken", "old"]
        assert not workspace.active
        assert workspace.closed

    asyncio.run(exercise())
