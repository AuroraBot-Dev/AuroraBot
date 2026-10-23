from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from aurora_agent import ToolExecutionError
from aurora_bot.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition, ToolOutput
from aurora_bot.runtime import assemble_runtime
from aurora_bot.tools import ToolRegistry
from aurora_bot.utils import configure_console_logging
from aurora_bot.world.config import resolve_storage_directory
from aurora_cli import load_config
from aurora_cli.configs.storage import CONFIG_SPEC as STORAGE_CONFIG
from aurora_cli.utils.logging import configure_project_logging
from tests.support.model import FakeModelDirectory

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.contracts import ToolResult


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
        raise ToolExecutionError("secret-in-exception")


@pytest.mark.parametrize("level", ("TRACE", "warn", "WARN", ""))
def test_logging_config_rejects_invalid_levels(
    configured_project: Path,
    level: str,
) -> None:
    (configured_project / "config" / "runtime.toml").write_text(
        (f'[runtime]\nprofile = "prod"\nagent = "aurora:agent/definition/root"\nlog_level = "{level}"\n'),
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
        await asyncio.wait_for(runtime.run("secret-in-message", run_id="logging-tree"), timeout=5)
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

    assert "认知运行开始 run_id=logging-tree" in content
    assert (
        "工具调用失败 tool=test:tool/definition/logging call_id=logging-call error_type=ToolExecutionError" in content
    )
    assert "secret-in-message" not in content
    assert "secret-in-model-result" not in content
    assert "secret-in-arguments" not in content
    assert "secret-in-exception" not in content
