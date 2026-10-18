"""大请求的执行前持久化、冲突核对与中断恢复。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest

from src.artifacts.store import FileArtifactStore
from src.contracts import ToolScopes
from src.contracts.artifact import ArtifactIntegrityError
from src.contracts.operation import (
    OperationDefinition,
    OperationKind,
    OperationRequest,
    OperationResult,
    OperationStatus,
)
from src.contracts.resource import ResourceAlias, ResourceKey, ResourceRef
from src.operations.registry import OperationRegistry
from src.operations.requests import DEFAULT_INLINE_REQUEST
from src.resources.catalog import ResourceCatalog
from src.utils.serialization import thaw_json
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from src.contracts.artifact import ArtifactInfo

_BOT = "lab:bot/persistent"
_TEXT = "完整原始参数" * (2 * DEFAULT_INLINE_REQUEST)


@dataclass(slots=True)
class ReceivingOperation:
    """只回报接收的内容与实际版本，不重复持久化大正文。"""

    revision: str = "1"
    kind: OperationKind = OperationKind.COMMAND
    calls: int = 0
    interrupt: bool = False

    @property
    def definition(self) -> OperationDefinition:
        """查询可重试，命令默认保留未知效果边界。"""
        return OperationDefinition(
            ResourceRef(ResourceKey("lab", "test", self.kind.value, "receive"), self.revision),
            "接收完整原始参数",
            {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
        )

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """测试动作不读取业务世界域。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """真实参数穿过路由后仍需完整，不允许用占位引用代替处理者输入。"""
        self.calls += 1
        if self.interrupt:
            self.interrupt = False
            raise asyncio.CancelledError
        text = request.arguments["items"][0]["text"]
        assert text == _TEXT
        return OperationResult({"size": len(text), "revision": request.target.revision})


def _request(operation: ReceivingOperation) -> OperationRequest:
    """嵌套数组、空值和文本一起参与同一请求身份的冲突检查。"""
    return OperationRequest(
        "receive",
        _BOT,
        "test",
        operation.definition.ref,
        operation.kind,
        {"items": [{"text": _TEXT}, [True, None, 1.5]]},
        correlation_id="experiment",
        caused_by="source",
    )


def test_large_request_is_compact_in_world_and_identical_retry_survives_restart(tmp_path: Path) -> None:
    """台账只保存固定引用，处理者与重试核对仍使用完整参数。"""

    async def scenario() -> None:
        operation = ReceivingOperation()
        request = _request(operation)
        catalog = ResourceCatalog((operation.definition.resource,))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        try:
            registry = OperationRegistry(
                _BOT, (operation,), catalog, world, artifacts=FileArtifactStore(tmp_path / "artifacts")
            )
            first = await registry.dispatch(request)
            page = await world.stream(0, 10)
            assert all(
                len(json.dumps(thaw_json(commit.data)).encode()) < DEFAULT_INLINE_REQUEST for commit in page.commits
            )
            assert (
                page.commits[0]
                .data["request"]["request_ref"]["media_type"]
                .startswith("application/vnd.aurora.operation-request")
            )
            await world.close()
            world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
            restarted = OperationRegistry(
                _BOT, (operation,), catalog, world, artifacts=FileArtifactStore(tmp_path / "artifacts")
            )
            assert await restarted.dispatch(request) == first
            assert operation.calls == 1
            for changed in (
                replace(request, arguments={"items": [{"text": _TEXT + "改"}]}),
                replace(request, correlation_id="different"),
                replace(request, caused_by="different"),
            ):
                with pytest.raises(ValueError, match="不同操作内容"):
                    await restarted.dispatch(changed)
            assert operation.calls == 1
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", list(OperationKind))
def test_interrupted_large_request_preserves_resolved_version_and_effect_uncertainty(
    tmp_path: Path, kind: OperationKind
) -> None:
    """查询沿已冻结版本重试；非幂等命令中断后不重复执行。"""

    async def scenario() -> None:
        first = ReceivingOperation(kind=kind, interrupt=True)
        second = ReceivingOperation("2", kind)
        alias = ResourceKey("lab", "test", kind.value, "default")
        resources = (first.definition.resource, second.definition.resource)
        before = ResourceCatalog(resources, (ResourceAlias(alias, first.definition.ref),))
        after = ResourceCatalog(resources, (ResourceAlias(alias, second.definition.ref),))
        request = replace(_request(first), target=ResourceRef(alias))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        store = FileArtifactStore(tmp_path / "artifacts")
        try:
            with pytest.raises(asyncio.CancelledError):
                await OperationRegistry(_BOT, (first, second), before, world, artifacts=store).dispatch(request)
            result = await OperationRegistry(_BOT, (first, second), after, world, artifacts=store).dispatch(request)
            if kind is OperationKind.QUERY:
                assert result.status is OperationStatus.SUCCEEDED
                assert result.data["revision"] == "1"
            else:
                assert result.status is OperationStatus.UNKNOWN
            expected_calls = 2 if kind is OperationKind.QUERY else 1
            assert first.calls == expected_calls
            assert second.calls == 0
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("damage", ["object", "binding"])
def test_missing_request_body_does_not_allow_replacement_or_repeat_effect(tmp_path: Path, damage: str) -> None:
    """调用方重新提供参数不能替代已丢失的原始请求事实。"""

    async def scenario() -> None:
        operation = ReceivingOperation()
        request = _request(operation)
        catalog = ResourceCatalog((operation.definition.resource,))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        try:
            registry = OperationRegistry(
                _BOT, (operation,), catalog, world, artifacts=FileArtifactStore(tmp_path / "artifacts")
            )
            await registry.dispatch(request)
            recorded = await world.commit(f"{request.identity}:requested")
            assert recorded is not None
            revision = recorded.data["request"]["request_ref"]["revision"]
            if damage == "object":
                next((tmp_path / "artifacts/objects").rglob(revision)).unlink()
            else:
                next((tmp_path / "artifacts/bindings").rglob(f"{revision}.json")).unlink()
            for retry in (request, replace(request, arguments={"items": [{"text": "替代内容"}]})):
                with pytest.raises(ArtifactIntegrityError, match="请求正文"):
                    await registry.dispatch(retry)
            assert operation.calls == 1
            assert await world.commit(f"{request.identity}:requested") == recorded
        finally:
            await world.close()

    asyncio.run(scenario())


def test_request_publish_failure_prevents_handler_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正文发布之前发生存储错误，不能提前写请求事实或开始动作。"""

    async def fail(key: ResourceKey, chunks: Iterable[bytes], *, media_type: str) -> ArtifactInfo:
        """模拟真实存储端口在发布前无法继续。"""
        raise OSError("磁盘无法写入")

    async def scenario() -> None:
        operation = ReceivingOperation()
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        store = FileArtifactStore(tmp_path / "artifacts")
        try:
            registry = OperationRegistry(
                _BOT, (operation,), ResourceCatalog((operation.definition.resource,)), world, artifacts=store
            )
            with monkeypatch.context() as patch:
                patch.setattr(store, "put_stream", fail)
                with pytest.raises(OSError, match="无法写入"):
                    await registry.dispatch(_request(operation))
            assert operation.calls == 0
            assert await world.cursor() == 0
            assert (await registry.dispatch(_request(operation))).status is OperationStatus.SUCCEEDED
            assert operation.calls == 1
        finally:
            await world.close()

    asyncio.run(scenario())
