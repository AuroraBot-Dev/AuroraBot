from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.localhost.command_types import CommandControl, InputOrigin, RuntimeInput
from src.localhost.runtime import AuroraRuntime
from src.utils.log_utils import configure_logging, get_logger

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_CONVERSATION_INPUTS = 2


def _input(text: str) -> RuntimeInput:
    return RuntimeInput(
        text=text,
        origin=InputOrigin.CONSOLE,
        session_id="test:console",
        source_app="tests.console",
        source_instance="commands",
        reply_capability="org.aurora.console.send_message",
    )


def test_runtime_router_separates_commands_from_conversation(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        try:
            before = len(runtime.kernel.tasks())
            status = await runtime.route_input(_input("/status"))
            unknown = await runtime.route_input(_input("/does-not-exist"))
            invalid = await runtime.route_input(_input("/pump 101"))
            bare = await runtime.route_input(_input("hello world"))
            quoted = await runtime.route_input(_input('/say "quoted message"'))
            quitting = await runtime.route_input(_input("/q"))

            assert status.ok and status.data is not None
            assert len(runtime.kernel.tasks()) == before
            assert not unknown.ok and "未知命令" in (unknown.text or "")
            assert not invalid.ok and "用法" in (invalid.text or "")
            assert bare.task_id is not None and not bare.publish_reply
            assert quoted.task_id is not None and not quoted.publish_reply
            assert quitting.control is CommandControl.SHUTDOWN_PROCESS
            assert (
                len(tuple(runtime.configuration.runtime.workspace.joinpath("inbox").glob("*.json")))
                == EXPECTED_CONVERSATION_INPUTS
            )
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_log_command_only_mutes_terminal_handlers(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        try:
            result = await runtime.route_input(_input("/log off --level debug"))
            assert result.data == {"enabled": False, "console_level": "debug", "file_level": "info"}

            logger = get_logger("aurora.test.runtime-log-command")
            marker = "file-audit-survives-console-off"
            logger.info(marker)
            for handler in logger.handlers:
                handler.flush()

            file_handlers = [handler for handler in logger.handlers if hasattr(handler, "baseFilename")]
            console_handlers = [handler for handler in logger.handlers if not hasattr(handler, "baseFilename")]
            assert file_handlers and all(handler.level == logging.INFO for handler in file_handlers)
            assert console_handlers and all(handler.level > logging.CRITICAL for handler in console_handlers)
            assert logging.getLogger("uvicorn.access").level > logging.CRITICAL
            assert marker in (project_root / "logs" / "aurora.log").read_text(encoding="utf-8")

            restored = await runtime.route_input(_input("/log on"))
            assert restored.data is not None and restored.data["enabled"] is True
            assert restored.data["console_level"] == "debug"
            assert logging.getLogger("uvicorn.access").level == logging.DEBUG
        finally:
            configure_logging("INFO")
            await runtime.shutdown()

    asyncio.run(scenario())
