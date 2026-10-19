"""Bot 通过真实工具与统一操作入口发现训练资源，无需事先知道版本。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel

from aurora import load_config
from src.contracts import ToolCall, ToolOutput, ToolStatus
from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.resources import ResourceCatalog
from src.contracts.pkgs.tools import ToolRegistry
from src.contracts.resource import ResourceKey, ResourceRef
from src.contracts.resource_query import MAX_RESOURCE_PAGE
from src.runtime import assemble_runtime

if TYPE_CHECKING:
    from pathlib import Path


_TOOL = "aurora:tool/definition/artifact_find"


def test_discovered_content_can_be_read_via_the_same_model_tools(configured_project: Path) -> None:
    """发现、继续和读取共享同一存储与固定版本，清单本身不生成正文证据。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        """用实际发布的两个权重版本演练模型可用的完整入口。"""
        try:
            store = runtime.assembly.get(ArtifactStore)
            key = ResourceKey.parse("lab:memory/model/tgn")
            expected = {await store.put(key, b"one"), await store.put(key, b"two")}
            tools = runtime.assembly.get(ToolRegistry)
            arguments = {"namespace": "lab", "kind": "model", "limit": 1}
            found = []
            for identity in ("first", "next"):
                output = await tools.execute(ToolCall(identity, _TOOL, arguments))
                assert isinstance(output, ToolOutput)
                assert output.status is ToolStatus.SUCCEEDED
                assert not output.evidence_refs
                data = json.loads(output.content)
                assert data["listing_mode"] == "live"
                assert data["content_verified"] is False
                assert len(data["items"]) == 1
                found.extend(data["items"])
                arguments = {**arguments, "after": data["next_cursor"]}
            assert data["next_cursor"] is None
            assert {item["revision"] for item in found} == {item.ref.revision for item in expected}
            content = await tools.execute(
                ToolCall(
                    "read",
                    "aurora:tool/definition/artifact_read",
                    {"key": found[0]["key"], "revision": found[0]["revision"], "encoding": "utf-8"},
                )
            )
            assert isinstance(content, ToolOutput)
            assert json.loads(content.content)["text"] in {"one", "two"}
            definition = runtime.assembly.get(ResourceCatalog).resolve(
                ResourceRef(ResourceKey.parse("aurora:artifacts/query/find"), "1")
            )
            assert definition.metadata["parameters"]["properties"]["limit"]["maximum"] == MAX_RESOURCE_PAGE
            terminal = await runtime.terminal.dispatch_terminal(
                '/call aurora:artifacts/query/find {"namespace":"lab","kind":"dataset"}'
            )
            assert not terminal.is_error
            assert json.loads(terminal.text or "{}")["data"]["items"] == []
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "arguments",
    [{"limit": 101}, {"limit": True}, {"namespace": "bad:name"}, {"after": "?"}, {"unexpected": "x"}],
)
def test_discovery_tool_reports_invalid_queries(configured_project: Path, arguments: dict[str, object]) -> None:
    """参数、筛选和游标无效时，工具返回失败而不是空结果。"""
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        """统一路由与处理者共同落实输入契约。"""
        try:
            output = await runtime.assembly.get(ToolRegistry).execute(ToolCall("invalid", _TOOL, arguments))
            assert isinstance(output, ToolOutput)
            assert output.status is ToolStatus.FAILED
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
