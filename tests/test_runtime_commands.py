from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.contracts.configuration import load_configuration
from src.localhost.command_types import CommandControl, InputOrigin, RuntimeInput
from src.localhost.runtime import AuroraRuntime
from src.utils.log_utils import configure_logging, get_logger

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_AMP_INPUTS = 3


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
        configuration = load_configuration(project_root)
        configure_logging(configuration.logging_level, configuration.root / "logs" / "aurora.log")
        runtime = AuroraRuntime.create(project_root, configuration=configuration)
        try:
            before = len(runtime.kernel.tasks())
            status = await runtime.route_input(_input("/status"))
            help_result = await runtime.route_input(_input("/help"))
            unknown = await runtime.route_input(_input("/does-not-exist"))
            invalid = await runtime.route_input(_input("/pump 101"))
            invalid_quote = await runtime.route_input(_input('/say "unterminated'))
            invalid_event_json = await runtime.route_input(_input("/event test.event --data nope"))
            invalid_event_shape = await runtime.route_input(_input("/event test.event --data '[]'"))
            event = await runtime.route_input(
                _input("/event test.event --summary 'ambient test' --data '{\"ambient\":true}'")
            )
            missing_task = await runtime.route_input(_input("/task missing"))
            missing_agent = await runtime.route_input(_input("/agent missing"))
            bare = await runtime.route_input(_input("hello world"))
            quoted = await runtime.route_input(_input('/say "quoted message"'))
            quitting = await runtime.route_input(_input("/q"))

            assert status.ok and status.data is not None
            assert len(runtime.kernel.tasks()) == before
            assert help_result.ok and "/event" in (help_result.text or "")
            assert not unknown.ok and "未知命令" in (unknown.text or "")
            assert not invalid.ok and "用法" in (invalid.text or "")
            assert not invalid_quote.ok and "命令解析失败" in (invalid_quote.text or "")
            assert not invalid_event_json.ok and "有效 JSON" in (invalid_event_json.text or "")
            assert not invalid_event_shape.ok and "JSON object" in (invalid_event_shape.text or "")
            assert event.message_id is not None
            assert not missing_task.ok and not missing_agent.ok
            assert bare.message_id is not None and not bare.publish_reply
            assert quoted.message_id is not None and not quoted.publish_reply
            assert quitting.control is CommandControl.SHUTDOWN_PROCESS
            assert (
                len(tuple(runtime.configuration.runtime.workspace.joinpath("inbox").glob("*.json")))
                == EXPECTED_AMP_INPUTS
            )

            pumped = await runtime.route_input(_input("/pump 1"))
            assert pumped.ok and pumped.data is not None
            task = runtime.kernel.tasks()[0]
            assert task.task_id not in {bare.message_id, quoted.message_id}
            task_result = await runtime.route_input(_input(f"/task {task.task_id}"))
            agent_result = await runtime.route_input(_input(f"/agent {task.root_agent_id}"))
            assert task_result.ok and task_result.data is not None
            assert agent_result.ok and agent_result.data is not None
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_log_command_only_mutes_terminal_handlers(project_root: Path) -> None:
    async def scenario() -> None:
        configuration = load_configuration(project_root)
        configure_logging(configuration.logging_level, configuration.root / "logs" / "aurora.log")
        runtime = AuroraRuntime.create(project_root, configuration=configuration)
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
