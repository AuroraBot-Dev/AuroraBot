"""大回执的独立内容、持久恢复与未知效果边界。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
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
from src.contracts.resource import ResourceKey, ResourceRef
from src.operations.receipts import DEFAULT_INLINE_RECEIPT
from src.operations.registry import OperationRegistry
from src.resources.catalog import ResourceCatalog
from src.utils.serialization import thaw_json
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

_BOT = "lab:bot/persistent"
_REF = ResourceRef(ResourceKey.parse("lab:experiment/command/finish"), "1")


@dataclass(slots=True)
class LargeOperation:
    """外部动作只执行一次，并产生大于台账内联上限的完整结果。"""

    result: OperationResult
    calls: int = 0

    @property
    def definition(self) -> OperationDefinition:
        """非幂等命令不能靠重放动作来补回丢失正文。"""
        return OperationDefinition(_REF, "完成实验", {"type": "object", "additionalProperties": False})

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """测试动作不读取其他世界域。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """保留效果次数以验证回执恢复。"""
        self.calls += 1
        return self.result


def _request() -> OperationRequest:
    """稳定请求身份跨进程恢复。"""
    return OperationRequest("finish", _BOT, "test", _REF, OperationKind.COMMAND)


def _result(status: OperationStatus = OperationStatus.SUCCEEDED) -> OperationResult:
    """大对象包含中文、嵌套不可变数组和独立证据引用。"""
    return OperationResult(
        {"history": [{"text": "真实经历" * (2 * DEFAULT_INLINE_RECEIPT)}], "conclusion": [True, None, 1.5]},
        status,
        None if status is OperationStatus.SUCCEEDED else "请核对实验结果",
        ("experiment-source",),
    )


@pytest.mark.parametrize("status", list(OperationStatus))
def test_large_receipt_keeps_world_small_and_restores_exact_result_after_restart(
    tmp_path: Path, status: OperationStatus
) -> None:
    """正文不进入世界流，重启后仍能恢复全部结果、状态和证据。"""

    async def scenario() -> None:
        operation = LargeOperation(_result(status))
        catalog = ResourceCatalog((operation.definition.resource,))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        artifacts = FileArtifactStore(tmp_path / "artifacts")
        try:
            registry = OperationRegistry(_BOT, (operation,), catalog, world, artifacts=artifacts)
            first = await registry.dispatch(_request())
            assert first.data == operation.result.data
            assert first.evidence_refs == operation.result.evidence_refs
            assert first.status is status
            assert first.body_ref is not None
            page = await world.stream(0, 10)
            receipt = page.commits[-1]
            assert len(json.dumps(thaw_json(receipt.data)).encode()) < DEFAULT_INLINE_RECEIPT
            assert "history" not in json.dumps(thaw_json(receipt.data))
            assert receipt.data["status"] == status.value
            assert receipt.data["result_ref"]["revision"] == first.body_ref.ref.revision
            await world.close()
            world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
            restarted = OperationRegistry(
                _BOT, (operation,), catalog, world, artifacts=FileArtifactStore(tmp_path / "artifacts")
            )
            assert await restarted.dispatch(_request()) == first
            assert operation.calls == 1
            assert len((await world.stream(0, 10)).commits) == len(page.commits)
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["missing", "missing_binding", "corrupt", "unconfigured"])
def test_unreadable_receipt_never_repeats_the_command_or_rewrites_its_status(tmp_path: Path, failure: str) -> None:
    """已提交结果的正文丢失，不等价于动作尚未执行。"""

    async def scenario() -> None:
        operation = LargeOperation(_result())
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        catalog = ResourceCatalog((operation.definition.resource,))
        artifacts = FileArtifactStore(tmp_path / "artifacts")
        try:
            registry = OperationRegistry(_BOT, (operation,), catalog, world, artifacts=artifacts)
            first = await registry.dispatch(_request())
            assert first.body_ref is not None
            path = next((tmp_path / "artifacts/objects").rglob(first.body_ref.ref.revision or ""))
            if failure == "missing":
                path.unlink()
            elif failure == "missing_binding":
                next((tmp_path / "artifacts/bindings").rglob("*.json")).unlink()
            elif failure == "corrupt":
                path.write_bytes(b"lost content")
            restarted = OperationRegistry(
                _BOT, (operation,), catalog, world, artifacts=None if failure == "unconfigured" else artifacts
            )
            with pytest.raises(ArtifactIntegrityError):
                await restarted.dispatch(_request())
            assert operation.calls == 1
            receipt = await world.commit(f"{_request().identity}:result")
            assert receipt is not None
            assert receipt.kind == "operation.succeeded"
            assert receipt.data["status"] == OperationStatus.SUCCEEDED.value
        finally:
            await world.close()

    asyncio.run(scenario())


def test_small_receipt_remains_inline_and_legacy_receipts_still_restore(tmp_path: Path) -> None:
    """小结果继续使用已有回执格式，内容存储不会制造冗余副本。"""

    async def scenario() -> None:
        operation = LargeOperation(OperationResult({"small": ["中文", {"value": 1}]}))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        catalog = ResourceCatalog((operation.definition.resource,))
        try:
            legacy = OperationRegistry(_BOT, (operation,), catalog, world)
            first = await legacy.dispatch(_request())
            restarted = OperationRegistry(
                _BOT, (operation,), catalog, world, artifacts=FileArtifactStore(tmp_path / "artifacts")
            )
            assert await restarted.dispatch(_request()) == first
            assert first.body_ref is None
            assert not (tmp_path / "artifacts").exists()
            new_request = OperationRequest("new", _BOT, "test", _REF, OperationKind.COMMAND)
            assert (await restarted.dispatch(new_request)).body_ref is None
            assert not (tmp_path / "artifacts").exists()
        finally:
            await world.close()

    asyncio.run(scenario())
