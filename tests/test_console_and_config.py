from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.contracts.configuration import load_configuration
from src.localhost.ports import PublicationExecutorBinding
from src.localhost.runtime import AuroraRuntime
from src.platform.console import CONSOLE_SEND_DESCRIPTOR, ConsolePlatform
from src.platform.console.shell import run_console
from src.utils.log_utils import configure_console_logging, configure_logging

if TYPE_CHECKING:
    from pathlib import Path


def test_configuration_is_an_explicit_immutable_snapshot(project_root: Path) -> None:
    snapshot = load_configuration(project_root)

    assert snapshot.runtime.workspace == project_root / "data" / "kernel"
    assert snapshot.model_definitions["fast"].model == "fast"
    assert snapshot.model_definitions["multimodal"].model == "multimodal"
    assert snapshot.model_definitions["embedding"].model == "embedding"


def test_layered_console_submits_and_processes_a_message(project_root: Path) -> None:
    async def scenario() -> list[str]:
        configuration = load_configuration(project_root)
        configure_logging(configuration.logging_level, configuration.root / "logs" / "aurora.log")
        configure_console_logging(enabled=False)
        runtime = AuroraRuntime.create(
            project_root,
            configuration=configuration,
            executor_bindings=None,
            publication_bindings=None,
        )
        console = ConsolePlatform()
        runtime.bind_platform_executors(
            (),
            (
                PublicationExecutorBinding(
                    CONSOLE_SEND_DESCRIPTOR,
                    console,
                    console,
                    "platform.console",
                    "test",
                ),
            ),
        )
        inputs = iter(("/log", "/say console hello", "/pump", "/quit"))
        output: list[str] = []
        try:
            await run_console(
                runtime,
                console,
                readline=lambda _prompt: next(inputs),
                output=output.append,
            )
            return output
        finally:
            await runtime.shutdown()
            console.close()

    output = asyncio.run(scenario())

    assert any('"enabled": false' in line for line in output)
    assert any("已投递消息 AMP" in line for line in output)
    assert any("effect_receipts_emitted" in line for line in output)
