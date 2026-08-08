from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from src.utils import (
    UnsupportedLoggingLevelError,
    configure_console_logging,
    configure_logging,
    console_logging_status,
    get_logger,
)
from src.utils import logging as aurora_logging

if TYPE_CHECKING:
    from pathlib import Path


def test_terminal_visibility_filter_does_not_hide_file_audit(tmp_path: Path) -> None:
    terminal = aurora_logging._create_stream_handler()
    logfile = tmp_path / "mcp.log"
    file_handler = aurora_logging._create_file_handler(logfile)
    record = logging.LogRecord("MCPServerKit", logging.INFO, __file__, 1, "child diagnostic", (), None)
    record.aurora_terminal = False
    try:
        assert terminal.filter(record) is False
        assert file_handler.filter(record)
        file_handler.handle(record)
    finally:
        terminal.close()
        file_handler.close()
    assert "child diagnostic" in logfile.read_text(encoding="utf-8")


def test_runtime_configuration_updates_existing_and_future_loggers(tmp_path: Path) -> None:
    logfile = tmp_path / "aurora.log"
    existing = get_logger("aurora.test.logging.existing")
    configure_logging("ERROR", logfile)
    future = get_logger("aurora.test.logging.future")

    assert existing.level == logging.ERROR
    assert future.level == logging.ERROR
    assert any(hasattr(handler, "baseFilename") for handler in existing.handlers)

    configure_console_logging(enabled=False, level="DEBUG")
    status = console_logging_status()
    assert status == {"enabled": False, "console_level": "debug", "file_level": "error"}
    marker = "file-audit-survives-console-off"
    existing.error(marker)
    for handler in existing.handlers:
        handler.flush()
    assert marker in logfile.read_text(encoding="utf-8")

    configure_console_logging(enabled=True)
    configure_logging("INFO")


def test_logging_levels_accept_warn_and_reject_unknown() -> None:
    assert aurora_logging._level_number("warn") == logging.WARNING
    assert aurora_logging._level_name(logging.DEBUG) == "DEBUG"
    with pytest.raises(UnsupportedLoggingLevelError):
        aurora_logging._level_number("verbose")
