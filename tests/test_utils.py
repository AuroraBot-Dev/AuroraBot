from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from src.utils import (
    UnsupportedLoggingLevelError,
    bounded_summary,
    configure_console_logging,
    configure_logging,
    console_logging_status,
    extract_json_from_text,
    get_logger,
    utc_now,
    utc_today,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_text_json_and_time_helpers_keep_small_shared_behaviors() -> None:
    assert bounded_summary([]) == "暂无摘要"
    assert bounded_summary(["甲", "乙"], limit=3) == "甲；乙"
    assert bounded_summary(["很长的文本"], limit=4) == "很长的…"
    assert extract_json_from_text('说明```json\n{"value": 1}\n```') == {"value": 1}
    assert extract_json_from_text('{"line": "a\nb"}') == {"line": "a\nb"}
    assert extract_json_from_text("没有 JSON") is None
    assert datetime.fromisoformat(utc_now()).tzinfo is not None
    assert date.fromisoformat(utc_today()) <= datetime.now(UTC).date()


def test_standard_logging_updates_console_and_rotating_file(tmp_path: Path) -> None:
    logfile = tmp_path / "logs" / "aurora.log"
    logger = get_logger("tests.utils.logging")

    configure_logging("INFO", logfile)
    configure_console_logging(enabled=False)
    logger.info("日志已写入")
    for handler in logger.handlers:
        handler.flush()

    assert "日志已写入" in logfile.read_text(encoding="utf-8")
    assert console_logging_status() == {
        "enabled": False,
        "console_level": "info",
        "file_level": "info",
    }
    configure_console_logging(enabled=True, level=logging.WARNING)
    assert console_logging_status()["console_level"] == "warning"


def test_logging_rejects_unknown_level() -> None:
    with pytest.raises(UnsupportedLoggingLevelError):
        configure_logging("NOT_A_LEVEL")
