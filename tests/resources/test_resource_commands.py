"""验证终端资源发现与调用复用领域操作定义。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from aurora_bot.runtime import assemble_runtime
from aurora_cli import load_config
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path


def test_terminal_discovers_inspects_and_calls_same_bot_operations(configured_project: Path) -> None:
    """终端读取与修改不经过 LLM，参数结构来自同一能力定义。"""

    async def scenario() -> None:
        model = FakeModel()
        runtime = assemble_runtime(load_config(configured_project), model, output=lambda _: None)
        try:
            discovered = await runtime.terminal.dispatch_terminal("/resources --domain bot --kind query")
            page = json.loads(discovered.text or "{}")
            entries = page["items"]
            assert page["next_cursor"] is None
            assert [item["resource"] for item in entries] == ["aurora:bot/query/state"]
            inspected = await runtime.terminal.dispatch_terminal("/inspect aurora:bot/command/goal_set@2")
            definition = json.loads(inspected.text or "{}")
            assert "expected_version" in definition["metadata"]["parameters"]["required"]
            payload = {
                "expected_version": 0,
                "goal_id": "aurora:goal/check",
                "purpose": "核对结果",
                "success_condition": "结果已确认",
            }
            call = await runtime.terminal.dispatch_terminal(
                f"/call aurora:bot/command/goal_set@2 {json.dumps(payload, ensure_ascii=False)}"
            )
            assert not call.is_error
            result = json.loads(call.text or "{}")
            assert result["status"] == "succeeded"
            assert result["revision"] == "2"
            read = await runtime.terminal.dispatch_terminal("/call aurora:bot/query/state {}")
            snapshot = json.loads(read.text or "{}")["data"]
            assert snapshot["goals"][0]["goal_id"] == payload["goal_id"]
            page = await runtime.world.stream(0, 100)
            requests = [item for item in page.commits if item.kind == "operation.requested"]
            assert all(item.source == "console" for item in requests)
            assert model.requests == []
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "command",
    [
        "/call",
        "/call aurora:bot/query/state not-json",
        "/call aurora:bot/query/state []",
        '/call aurora:bot/query/state {"unexpected":true}',
        "/call aurora:bot/command/missing {}",
        "/inspect aurora:bot/query/state@missing",
        "/resources --domain",
        "/resources --unknown bot",
        "/resources --domain bot --domain bot",
    ],
)
def test_invalid_resource_commands_leave_subject_unchanged(configured_project: Path, command: str) -> None:
    """语法或参数无效时报告错误，不产生目标修改。"""

    async def scenario() -> None:
        runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)
        try:
            response = await runtime.terminal.dispatch_terminal(command)
            assert response.is_error
            assert (await runtime.assembly.get("bot").snapshot()).goals == ()
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
