from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from src.ai.contracts import ModelGatewayError, ModelMessage, ModelRequest
from src.ai.vnext import ModelGatewayService
from src.localhost.configuration import load_configuration
from src.localhost.runtime import AuroraRuntime
from src.utils.log_utils import configure_logging, get_logger
from tests.test_events import valid_amp

if TYPE_CHECKING:
    from pathlib import Path


class RecordHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_runtime_configuration_updates_existing_and_future_utils_loggers() -> None:
    existing = get_logger("aurora.test.logging.existing")
    configure_logging("ERROR")
    future = get_logger("aurora.test.logging.future")

    assert existing.level == logging.ERROR
    assert future.level == logging.ERROR
    assert all(handler.level == logging.ERROR for handler in existing.handlers)
    assert all(handler.level == logging.ERROR for handler in future.handlers)

    configure_logging("INFO")


def test_causal_logs_have_correlation_ids_without_amp_content(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = AuroraRuntime.create(project_root)
        configure_logging("DEBUG")
        handler = RecordHandler()
        loggers = [
            get_logger("aurora.kernel"),
            get_logger("aurora.runtime"),
            get_logger("aurora.platform.local"),
        ]
        for item in loggers:
            item.addHandler(handler)
        amp = valid_amp()
        amp["payload"]["summary"] = "TOP-SECRET-CONTENT"
        amp["payload"]["data"] = {"text": "TOP-SECRET-CONTENT"}
        try:
            await runtime.submit_amp(amp)
            await runtime.run_cycle()
        finally:
            for item in loggers:
                item.removeHandler(handler)
            await runtime.shutdown()
            configure_logging("INFO")

        messages = "\n".join(record.getMessage() for record in handler.records)
        assert "TOP-SECRET-CONTENT" not in messages
        assert "record_id=" in messages
        assert "episode_id=" in messages
        assert "cycle=" in messages

    asyncio.run(scenario())


def test_model_gateway_logs_metadata_without_prompt_content(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        monkeypatch.delenv("AURORA_TEST_MODEL_API_KEY", raising=False)
        service = ModelGatewayService(load_configuration(project_root))
        configure_logging("DEBUG")
        handler = RecordHandler()
        gateway_logger = get_logger("aurora.model_gateway")
        gateway_logger.addHandler(handler)
        try:
            with pytest.raises(ModelGatewayError, match="missing model credential"):
                await service.complete(
                    ModelRequest(
                        role="fast",
                        messages=(ModelMessage("user", "PRIVATE-PROMPT-CONTENT"),),
                        parameters={"temperature": 0.2},
                    )
                )
        finally:
            gateway_logger.removeHandler(handler)
            configure_logging("INFO")

        messages = "\n".join(record.getMessage() for record in handler.records)
        assert "PRIVATE-PROMPT-CONTENT" not in messages
        assert "messages=1" in messages
        assert "parameter_keys=['temperature']" in messages

    asyncio.run(scenario())
