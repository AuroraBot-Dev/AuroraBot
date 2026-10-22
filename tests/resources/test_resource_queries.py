"""终端与 Bot 通过统一操作发现、继续、检查未加载的资源版本。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import ToolCall, ToolOutput, ToolStatus
from aurora_bot.contracts.resource import ResourceKey
from aurora_bot.runtime import assemble_runtime
from aurora_cli import load_config
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path


def test_terminal_and_bot_share_live_resource_pages_and_inspection(configured_project: Path) -> None:
    """同一筛选条件得到同一续页和版本；查询本身有明确的世界调用记录。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        """发布、跨入口翻页、核对和读取均使用实际选中的内容存储。"""
        try:
            store = runtime.assembly.get("artifacts")
            key = ResourceKey.parse("lab:memory/dataset/episodes")
            versions = (await store.put(key, b"first"), await store.put(key, b"second"))
            tools = runtime.assembly.get("tools")
            arguments = {"namespace": "lab", "limit": 1}
            first = await tools.execute(ToolCall("find", "aurora:tool/definition/resources_find", arguments))
            assert isinstance(first, ToolOutput)
            assert first.status is ToolStatus.SUCCEEDED
            assert first.evidence_refs == ()
            data = json.loads(first.content)
            terminal = await runtime.terminal.dispatch_terminal("/resources --namespace lab --limit 1")
            assert not terminal.is_error
            assert json.loads(terminal.text or "{}") == data
            assert data["listing_mode"] == "live"
            selected = data["items"][0]
            continued = await runtime.terminal.dispatch_terminal(
                f"/resources --namespace lab --limit 1 --after {data['next_cursor']}"
            )
            remaining = json.loads(continued.text or "{}")
            assert remaining["next_cursor"] is None
            assert {selected["revision"], remaining["items"][0]["revision"]} == {info.ref.revision for info in versions}
            inspected = await tools.execute(
                ToolCall(
                    "inspect",
                    "aurora:tool/definition/resources_inspect",
                    {"resource": selected["resource"], "revision": selected["revision"]},
                )
            )
            assert isinstance(inspected, ToolOutput)
            assert inspected.evidence_refs == ()
            descriptor = json.loads(inspected.content)
            assert descriptor["metadata"]["content_verified"] is True
            terminal_inspect = await runtime.terminal.dispatch_terminal(
                f"/inspect {selected['resource']}@{selected['revision']}"
            )
            assert json.loads(terminal_inspect.text or "{}") == descriptor
            body = await tools.execute(
                ToolCall(
                    "body",
                    "aurora:tool/definition/artifact_read",
                    {"key": selected["resource"], "revision": selected["revision"], "encoding": "utf-8"},
                )
            )
            assert isinstance(body, ToolOutput)
            assert json.loads(body.content)["text"] in {"first", "second"}
            page = await runtime.world.stream(0, 100)
            queried = [commit for commit in page.commits if commit.kind == "operation.requested"]
            assert all(commit.data["resolved"] is not None for commit in queried)
            assert any(commit.source == "console" for commit in queried)
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "command",
    [
        "/resources --limit many",
        "/resources --limit 0",
        "/resources --limit 101",
        "/resources --limit 1 --limit 2",
        "/resources --after ?",
        "/inspect lab:memory/model/tgn",
        '/call aurora:resources/query/inspect {"resource":"lab:memory/model/tgn",'
        '"contract":"lab:memory/contract/reader"}',
    ],
)
def test_invalid_resource_discovery_commands_report_errors(configured_project: Path, command: str) -> None:
    """分页、未固定动态版本和不完整契约条件不能被悄悄忽略。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        """公共操作校验与终端参数解析共同保护查询语义。"""
        try:
            response = await runtime.terminal.dispatch_terminal(command)
            assert response.is_error
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
