"""验证统一调用的输入校验、回执重试和中断边界。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import ToolScopes
from aurora_bot.contracts.operation import (
    OperationDefinition,
    OperationKind,
    OperationRequest,
    OperationResult,
    OperationStatus,
)
from aurora_bot.contracts.resource import ResourceAlias, ResourceKey, ResourceRef
from aurora_bot.operations.registry import OperationRegistry
from aurora_bot.resources.catalog import ResourceCatalog
from aurora_bot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
_BOT = "aurora:bot/test"


@dataclass(slots=True)
class CountingOperation:
    """可模拟执行中断、异常及正常结果的领域处理者。"""

    definition: OperationDefinition
    calls: int = 0
    interrupt: bool = False
    failure: bool = False

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """返回当前处理者声明的业务观察域。"""
        return ToolScopes(observe=frozenset({request.bot_id}))

    async def execute(self, request: OperationRequest) -> OperationResult:
        """记录调用次数，并按测试指定的路径结束。"""
        self.calls += 1
        if self.interrupt:
            self.interrupt = False
            raise asyncio.CancelledError
        if self.failure:
            raise RuntimeError("外部结果未确认")
        return OperationResult({"value": request.arguments["value"], "revision": request.target.revision})


def _operation(kind: OperationKind = OperationKind.COMMAND, revision: str = "1") -> CountingOperation:
    """构造有明确结构和确定版本的测试操作。"""
    return CountingOperation(
        OperationDefinition(
            ResourceRef(ResourceKey("lab", "test", kind.value, "echo"), revision),
            "回显",
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
    )


def _request(operation: CountingOperation) -> OperationRequest:
    """为同一来源构造一个可重试的请求。"""
    return OperationRequest(
        "request", _BOT, "test", operation.definition.ref, operation.definition.kind, {"value": "好"}
    )


@asynccontextmanager
async def _runtime(
    tmp_path: Path, operation: CountingOperation
) -> AsyncIterator[tuple[OperationRegistry, SqlAlchemyWorldJournal]]:
    """让测试只使用临时世界日志，确保连接始终释放。"""
    world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
    resources = ResourceCatalog((operation.definition.resource,))
    registry = OperationRegistry(_BOT, (operation,), resources, world, now=lambda: _NOW)
    try:
        yield registry, world
    finally:
        await world.close()


def test_completed_request_is_replayed_from_receipt_without_repeating_effect(tmp_path: Path) -> None:
    """新的路由实例也复用持久回执，不再次执行处理者。"""

    async def scenario() -> None:
        operation = _operation()
        async with _runtime(tmp_path, operation) as (registry, world):
            request = _request(operation)
            first = await registry.dispatch(request)
            restarted = OperationRegistry(_BOT, (operation,), ResourceCatalog((operation.definition.resource,)), world)
            assert await restarted.dispatch(request) == first
            assert operation.calls == 1
            page = await world.stream(0, 10)
            assert [commit.kind for commit in page.commits] == ["operation.requested", "operation.succeeded"]
            assert registry.scopes_for(request).observe == frozenset({_BOT})
            with pytest.raises(ValueError, match="不同操作内容"):
                await restarted.dispatch(replace(request, arguments={"value": "另一项意图"}))

    asyncio.run(scenario())


def test_interrupted_non_idempotent_command_is_not_executed_again(tmp_path: Path) -> None:
    """请求已登记但结果未知时，不能假定外部效果没有发生。"""

    async def scenario() -> None:
        operation = _operation()
        operation.interrupt = True
        async with _runtime(tmp_path, operation) as (registry, world):
            request = _request(operation)
            with pytest.raises(asyncio.CancelledError):
                await registry.dispatch(request)
            restarted = OperationRegistry(_BOT, (operation,), ResourceCatalog((operation.definition.resource,)), world)
            assert (await restarted.dispatch(request)).status is OperationStatus.UNKNOWN
            assert operation.calls == 1
            assert (await restarted.dispatch(request)).status is OperationStatus.UNKNOWN

    asyncio.run(scenario())


def test_interrupted_query_uses_frozen_version_even_after_alias_changes(tmp_path: Path) -> None:
    """别名变更不改变已经开始的一次读取所使用的版本。"""

    async def scenario() -> None:
        first = _operation(OperationKind.QUERY, "1")
        second = _operation(OperationKind.QUERY, "2")
        first.interrupt = True
        key = ResourceKey.parse("aurora:test/query/default")
        definitions = (first.definition.resource, second.definition.resource)
        before = ResourceCatalog(definitions, (ResourceAlias(key, first.definition.ref),))
        after = ResourceCatalog(definitions, (ResourceAlias(key, second.definition.ref),))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        try:
            request = replace(_request(first), target=ResourceRef(key))
            with pytest.raises(asyncio.CancelledError):
                await OperationRegistry(_BOT, (first, second), before, world).dispatch(request)
            result = await OperationRegistry(_BOT, (first, second), after, world).dispatch(request)
            assert result.data["revision"] == "1"
            assert second.calls == 0
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", [OperationKind.COMMAND, OperationKind.QUERY])
def test_handler_exception_preserves_side_effect_uncertainty(tmp_path: Path, kind: OperationKind) -> None:
    """命令异常标记未知，查询异常可以明确报告失败。"""

    async def scenario() -> None:
        operation = _operation(kind)
        operation.failure = True
        async with _runtime(tmp_path, operation) as (registry, _world):
            result = await registry.dispatch(_request(operation))
            expected = OperationStatus.UNKNOWN if kind is OperationKind.COMMAND else OperationStatus.FAILED
            assert result.status is expected

    asyncio.run(scenario())


def test_invalid_inputs_and_expired_deadline_never_reach_handler(tmp_path: Path) -> None:
    """格式、调用种类和期限在领域执行前校验。"""

    async def scenario() -> None:
        operation = _operation()
        async with _runtime(tmp_path, operation) as (registry, _world):
            request = _request(operation)
            invalid = replace(request, request_id="invalid", arguments={"value": 1})
            mismatched = replace(request, request_id="mismatch", kind=OperationKind.QUERY)
            expired = replace(request, request_id="expired", deadline_at=_NOW - timedelta(seconds=1))
            for item in (invalid, mismatched, expired):
                assert (await registry.dispatch(item)).status is OperationStatus.FAILED
            assert operation.calls == 0
            with pytest.raises(ValueError, match="不属于"):
                await registry.dispatch(replace(request, bot_id="aurora:bot/other"))

    asyncio.run(scenario())


def test_remote_schema_references_are_rejected_without_network(tmp_path: Path) -> None:
    """离线校验不能因扩展声明而发出网络请求。"""
    operation = _operation()
    operation.definition = replace(operation.definition, parameters={"$ref": "https://example.invalid/schema.json"})
    world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
    with pytest.raises(ValueError, match="本地引用"):
        OperationRegistry(_BOT, (operation,), ResourceCatalog((operation.definition.resource,)), world)


def test_operations_can_call_other_operations_without_blocking_the_registry(tmp_path: Path) -> None:
    """模组之间的查询可以组合，同一请求的重试仍只执行一次。"""

    async def scenario() -> None:
        child = _operation(OperationKind.QUERY)
        child.definition = replace(child.definition, ref=ResourceRef(ResourceKey.parse("lab:test/query/child"), "1"))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")

        class ParentOperation(CountingOperation):
            """通过公共协议读取另一个能力。"""

            async def execute(self, request: OperationRequest) -> OperationResult:
                """组合子操作的结果，保留独立调用身份。"""
                self.calls += 1
                nested = replace(request, request_id="child-request", target=child.definition.ref)
                return await registry.dispatch(nested)

        parent = ParentOperation(_operation(OperationKind.QUERY).definition)
        resources = ResourceCatalog((parent.definition.resource, child.definition.resource))
        registry = OperationRegistry(_BOT, (parent, child), resources, world)
        try:
            request = _request(parent)
            results = await asyncio.wait_for(asyncio.gather(registry.dispatch(request), registry.dispatch(request)), 1)
            assert results[0] == results[1]
            assert parent.calls == child.calls == 1
        finally:
            await world.close()

    asyncio.run(scenario())
