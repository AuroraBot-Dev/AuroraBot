from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.configs.storage import CONFIG_SPEC as STORAGE_CONFIG
from aurora.utils.logging import configure_project_logging
from aurorabot.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition, ToolOutput
from aurorabot.runtime import assemble_runtime
from aurorabot.tools import ToolRegistry
from aurorabot.utils import configure_console_logging
from aurorabot.world.config import resolve_storage_directory
from tests.support.model import FakeModelDirectory

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.contracts import ToolResult


@dataclass(slots=True)
class _Model(FakeModelDirectory):
    result: str

    async def complete(self, request: ModelRequest) -> ChatMessage:
        del request
        return ChatMessage.assistant(self.result)


class _FailingTool:
    definition = ToolDefinition(
        "test:tool/definition/logging",
        "日志边界测试工具",
        {"type": "object", "properties": {"token": {"type": "string"}}},
    )

    async def execute(self, call: ToolCall) -> ToolResult:
        del call
        raise RuntimeError("secret-in-exception")


@pytest.mark.parametrize("level", ("TRACE", "warn", "WARN", ""))
def test_logging_config_rejects_invalid_levels(
    configured_project: Path,
    level: str,
) -> None:
    (configured_project / "config" / "runtime.toml").write_text(
        (
            '[runtime]\nprofile = "prod"\nnode_id = "root"\n'
            f'agent = "aurora:agent/definition/root"\nlog_level = "{level}"\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_config(configured_project)


def test_runtime_logs_lifecycle_without_message_result_arguments_or_exception_details(
    configured_project: Path,
) -> None:
    config = load_config(configured_project)
    configure_project_logging(config)
    configure_console_logging(enabled=False)
    runtime = assemble_runtime(config, _Model("secret-in-model-result"))

    async def scenario() -> None:
        await asyncio.wait_for(runtime.run("secret-in-message", tree_id="logging-tree"), timeout=5)
        result = await ToolRegistry((_FailingTool(),)).execute(
            ToolCall("logging-call", "test:tool/definition/logging", {"token": "secret-in-arguments"})
        )
        assert isinstance(result, ToolOutput)
        assert result.is_error
        await runtime.world.close()

    asyncio.run(scenario())
    logfile = (
        configured_project
        / resolve_storage_directory(load_config(configured_project).get(STORAGE_CONFIG).entries, "logs")
        / "aurora.log"
    )
    content = logfile.read_text(encoding="utf-8")

    assert "AgentTree 开始 tree_id=logging-tree" in content
    assert "工具调用失败 tool=test:tool/definition/logging call_id=logging-call error_type=RuntimeError" in content
    assert "secret-in-message" not in content
    assert "secret-in-model-result" not in content
    assert "secret-in-arguments" not in content
    assert "secret-in-exception" not in content
