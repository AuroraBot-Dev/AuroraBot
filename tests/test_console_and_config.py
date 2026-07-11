from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.config import Config, load_config
from src.localhost.runtime import AuroraRuntime
from src.localhost.shell import run_console

if TYPE_CHECKING:
    from pathlib import Path


def test_public_config_facade_uses_the_validated_toml_snapshot(project_root: Path) -> None:
    snapshot = Config.reload(project_root)

    assert snapshot == load_config(project_root)
    assert project_root / "data" / "kernel" == Config.KERNEL_DATA_DIR
    assert Config.LLM_GATEWAY_FAST_MODEL == "test/fast"
    assert Config.LLM_GATEWAY_MULTIMODAL_MODEL == "test/multimodal"
    assert Config.LLM_GATEWAY_EMBEDDING_MODEL == "test/embedding"
    assert snapshot.model_logging.log_queries == Config.LLM_GATEWAY_ENABLE_LOGGING_QUERIES
    assert snapshot.model_logging.log_responses == Config.LLM_GATEWAY_ENABLE_LOGGING_RESPONSES


def test_layered_console_submits_and_processes_a_message(project_root: Path) -> None:
    runtime = AuroraRuntime.create(project_root)
    inputs = iter(("/say console hello", "/cycle", "/quit"))
    output: list[str] = []

    asyncio.run(run_console(runtime, readline=lambda _prompt: next(inputs), output=output.append))

    assert any("已投递消息 AMP" in line for line in output)
    assert any("platform_receipts_emitted" in line for line in output)
