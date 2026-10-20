from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aurora import load_config
from aurora.configs.runtime import CONFIG_SPEC as RUNTIME_CONFIG
from aurora.configs.storage import CONFIG_SPEC as STORAGE_CONFIG
from aurora.utils.logging import configure_project_logging
from aurorabot.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition, ToolOutput
from aurorabot.runtime import assemble_runtime
from aurorabot.tools import ToolRegistry
from aurorabot.utils import configure_console_logging
from aurorabot.world.config import resolve_storage_directory
from tests.model_support import FakeModelDirectory

if TYPE_CHECKING:
    from aurorabot.contracts import ToolResult

_ROOT = Path(__file__).parents[1]
_LOGGED_RUNTIME_MODULES = (
    "src/aurorabot/kernel/compose.py",
    "src/aurorabot/runtime/core.py",
    "src/aurorabot/runtime/run.py",
    "src/aurorabot/agents/catalog.py",
    "src/aurorabot/ai/gateway.py",
    "src/aurorabot/cadence/cadence.py",
    "src/aurorabot/console/shell.py",
    "src/aurorabot/engine/runtime.py",
    "src/aurorabot/mcp/client.py",
    "src/aurorabot/mcp/runtime.py",
    "src/aurorabot/mcp/tool.py",
    "src/aurorabot/memory/memory.py",
    "src/aurorabot/tools/registry.py",
    "src/aurorabot/world/store.py",
)


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


def test_logging_config_is_typed_and_project_relative(configured_project: Path) -> None:
    runtime = load_config(configured_project).get(RUNTIME_CONFIG)

    assert runtime.log_level == "INFO"
    storage = load_config(configured_project).get(STORAGE_CONFIG).entries
    assert resolve_storage_directory(storage, "logs") == "data/logs"


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


def test_key_runtime_modules_use_the_unified_logging_facility() -> None:
    violations: list[str] = []
    for relative in _LOGGED_RUNTIME_MODULES:
        tree = ast.parse((_ROOT / relative).read_text(encoding="utf-8"))
        imports_facility = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "aurorabot.utils"
            and any(alias.name == "get_logger" for alias in node.names)
            for node in ast.walk(tree)
        )
        emits = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"debug", "info", "warning", "error", "critical"}
            for node in ast.walk(tree)
        )
        if not imports_facility or not emits:
            violations.append(relative)

    assert violations == []
