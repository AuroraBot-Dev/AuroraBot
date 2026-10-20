"""工具和终端接收大结果引用，不把未展开正文当作证据曝光。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurorabot.artifacts.operations import ArtifactOperation
from aurorabot.artifacts.store import FileArtifactStore
from aurorabot.contracts import ToolCall, ToolStatus
from aurorabot.contracts.artifact_codec import read_artifact
from aurorabot.contracts.operation import OperationKind, OperationRequest, OperationResult, OperationStatus
from aurorabot.operations.registry import OperationRegistry
from aurorabot.operations.tool import OperationTool
from aurorabot.resources.catalog import ResourceCatalog
from aurorabot.runtime.resource_commands import ResourceCommands
from aurorabot.world import SqlAlchemyWorldJournal
from tests.operations.support import LargeOperation

if TYPE_CHECKING:
    from pathlib import Path

_BOT = "lab:bot/persistent"
_TEXT = "正文中的证据" * 12000


@pytest.mark.parametrize("status", list(OperationStatus))
def test_large_tool_output_is_bounded_and_does_not_claim_unread_evidence(
    tmp_path: Path, status: OperationStatus
) -> None:
    """状态保留，证据引用只有正文真正进入上下文后才能参与记忆审计。"""

    async def scenario() -> None:
        operation = LargeOperation(OperationResult({"text": _TEXT}, status, "完整结果说明", ("source",)))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        artifacts = FileArtifactStore(tmp_path / "artifacts")
        registry = OperationRegistry(
            _BOT, (operation,), ResourceCatalog((operation.definition.resource,)), world, artifacts=artifacts
        )
        definition = replace(operation.definition, tool_name="lab:tool/definition/finish")
        tool = OperationTool(registry, definition, _BOT)
        call = ToolCall("finish", "lab:tool/definition/finish", {})
        try:
            output = await tool.execute(call)
            assert output.status is ToolStatus(status.value)
            assert not output.evidence_refs
            assert _TEXT not in output.content
            body = json.loads(output.content)
            assert not body["content_included"]
            assert body["read_tool"] == "aurora:tool/definition/artifact_read"
            info = read_artifact(body["result_ref"])
            assert info.size > len(output.content.encode())
            assert await tool.execute(call) == output
            assert operation.calls == 1
            reader = ArtifactOperation(artifacts, "read")
            read = OperationRequest(
                "first-chunk",
                _BOT,
                "test",
                reader.definition.ref,
                OperationKind.QUERY,
                body["read_arguments"],
            )
            chunk = await reader.execute(read)
            expected = await artifacts.read(info.ref, limit=4096)
            assert chunk.data["encoding"] == "utf-8"
            assert expected.content.startswith(chunk.data["text"].encode())
            assert chunk.data["next_offset"] == len(chunk.data["text"].encode())
            assert chunk.data["has_more"]
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", list(OperationStatus))
def test_terminal_large_result_returns_reference_and_preserves_error_status(
    tmp_path: Path, status: OperationStatus
) -> None:
    """终端只序列化紧凑元信息，失败和未知结果也能继续展开正文。"""

    async def scenario() -> None:
        operation = LargeOperation(OperationResult({"text": _TEXT}, status, _TEXT, ("source",)))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        catalog = ResourceCatalog((operation.definition.resource,))
        registry = OperationRegistry(
            _BOT, (operation,), catalog, world, artifacts=FileArtifactStore(tmp_path / "artifacts")
        )
        commands = ResourceCommands(registry, _BOT)
        try:
            response = await commands.dispatch(f"/call {operation.definition.ref.key}@1 {{}}")
            assert response.text is not None
            body = json.loads(response.text)
            assert body["status"] == status.value
            assert body["data"] is None
            assert body["message"] is None
            assert not body["content_included"]
            assert body["read_operation"] == "aurora:artifacts/query/read"
            assert read_artifact(body["result_ref"]).size > len(response.text.encode())
            assert response.is_error is (status is not OperationStatus.SUCCEEDED)
            assert _TEXT not in response.text
        finally:
            await world.close()

    asyncio.run(scenario())


def test_small_tool_result_keeps_actual_evidence_and_existing_shape(tmp_path: Path) -> None:
    """完整显示的小回执仍携带原来的证据来源。"""

    async def scenario() -> None:
        operation = LargeOperation(OperationResult({"text": "短结果"}, evidence_refs=("source",)))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        try:
            registry = OperationRegistry(
                _BOT,
                (operation,),
                ResourceCatalog((operation.definition.resource,)),
                world,
                artifacts=FileArtifactStore(tmp_path / "artifacts"),
            )
            definition = replace(operation.definition, tool_name="lab:tool/definition/finish")
            output = await OperationTool(registry, definition, _BOT).execute(
                ToolCall("small", "lab:tool/definition/finish", {})
            )
            assert json.loads(output.content) == {"text": "短结果"}
            assert output.evidence_refs == ("source",)
        finally:
            await world.close()

    asyncio.run(scenario())
