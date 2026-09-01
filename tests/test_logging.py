from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aurora import assemble_runtime, load_config
from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.configuration.storage import STORAGE_CONFIG
from aurora.runtime.support import configure_project_logging
from src.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition, ToolOutput
from src.tools import ToolRegistry
from src.utils import configure_console_logging

if TYPE_CHECKING:
    from src.contracts import ToolResult

_ROOT = Path(__file__).parents[1]
_LOGGED_RUNTIME_MODULES = (
    "aurora/composer.py",
    "aurora/runtime/core.py",
    "aurora/runtime/run.py",
    "src/agents/catalog.py",
    "src/ai/gateway.py",
    "src/cadence/cadence.py",
    "src/console/shell.py",
    "src/engine/runtime.py",
    "src/mcp/client.py",
    "src/mcp/runtime.py",
    "src/mcp/tool.py",
    "src/memory/memory.py",
    "src/tools/registry.py",
    "src/world/store.py",
)


@dataclass(slots=True)
class _Model:
    result: str

    async def complete(self, request: ModelRequest) -> ChatMessage:
        del request
        return ChatMessage.assistant(self.result)


class _FailingTool:
    definition = ToolDefinition(
        "aur.test.logging",
        "日志边界测试工具",
        {"type": "object", "properties": {"token": {"type": "string"}}},
    )

    async def execute(self, call: ToolCall) -> ToolResult:
        del call
        raise RuntimeError("secret-in-exception")


def test_logging_configuration_is_typed_and_project_relative(configured_project: Path) -> None:
    runtime = load_config(configured_project).get(RUNTIME_CONFIG)

    assert runtime.log_level == "INFO"
    storage = load_config(configured_project).get(STORAGE_CONFIG)
    assert storage.resolve("logs") == "data/logs"


@pytest.mark.parametrize("level", ("TRACE", "warn", "WARN", ""))
def test_logging_configuration_rejects_invalid_levels(
    configured_project: Path,
    level: str,
) -> None:
    (configured_project / "config" / "runtime.toml").write_text(
        (f'[runtime]\nprofile = "prod"\nnode_id = "root"\nagent = "builtin.root"\nlog_level = "{level}"\n'),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_config(configured_project)


def test_runtime_logs_lifecycle_without_message_result_arguments_or_exception_details(
    configured_project: Path,
) -> None:
    configuration = load_config(configured_project)
    configure_project_logging(configuration)
    configure_console_logging(enabled=False)
    runtime = assemble_runtime(configuration, _Model("secret-in-model-result"))

    async def scenario() -> None:
        await asyncio.wait_for(runtime.run("secret-in-message", tree_id="logging-tree"), timeout=5)
        result = await ToolRegistry((_FailingTool(),)).execute(
            ToolCall("logging-call", "aur.test.logging", {"token": "secret-in-arguments"})
        )
        assert isinstance(result, ToolOutput)
        assert result.is_error
        await runtime.world.close()

    asyncio.run(scenario())
    logfile = configured_project / load_config(configured_project).get(STORAGE_CONFIG).resolve("logs") / "aurora.log"
    content = logfile.read_text(encoding="utf-8")

    assert "AgentTree 开始 tree_id=logging-tree" in content
    assert "工具调用失败 tool=aur.test.logging call_id=logging-call error_type=RuntimeError" in content
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
            and node.module == "src.utils"
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
