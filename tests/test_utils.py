from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from src.utils import (
    NamePatternError,
    UnsupportedLoggingLevelError,
    bounded_summary,
    configure_console_logging,
    configure_logging,
    console_logging_status,
    extract_json_from_text,
    get_logger,
    pattern_matches,
    resolve_names,
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


_TOOLS = frozenset(
    {
        "aur.agent.delegate",
        "aur.mcp.org.aurora.qq.qq_send_private_message",
        "aur.mcp.org.aurora.qq.qq_send_group_message",
        "aur.mcp.org.aurora.clock.get_current_time",
        "aur.serv.world.read",
        "aur.serv.world.trees",
    }
)


def test_resolve_names_applies_ordered_patterns_with_last_match_wins() -> None:
    assert resolve_names(_TOOLS, ("aur.agent.delegate", "aur.serv.world.*")) == frozenset(
        {"aur.agent.delegate", "aur.serv.world.read", "aur.serv.world.trees"}
    )
    assert resolve_names(_TOOLS, ("aur.mcp.org.aurora.qq.*", "!aur.mcp.org.aurora.qq.qq_send_group_message")) == (
        frozenset({"aur.mcp.org.aurora.qq.qq_send_private_message"})
    )
    assert resolve_names(_TOOLS, ("!aur.mcp.org.aurora.qq.*",)) == frozenset()
    assert resolve_names(_TOOLS, ("aur.**",)) == _TOOLS
    assert resolve_names(_TOOLS, ("aur.mcp.org.aurora.qq.qq_send_*_message",)) == frozenset(
        {"aur.mcp.org.aurora.qq.qq_send_private_message", "aur.mcp.org.aurora.qq.qq_send_group_message"}
    )
    assert resolve_names(_TOOLS, ("aur.mcp.org.aurora.qq.qq_send_?rivate_message",)) == frozenset(
        {"aur.mcp.org.aurora.qq.qq_send_private_message"}
    )
    assert resolve_names(_TOOLS, ("aur.mcp.org.aurora.qq.qq_send_[gp]rivate_message",)) == frozenset(
        {"aur.mcp.org.aurora.qq.qq_send_private_message"}
    )
    assert resolve_names(_TOOLS, ("aur.mcp.**.read",)) == frozenset()
    assert resolve_names(_TOOLS, ()) == frozenset()


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_resolve_names_rejects_unmatched_exact_and_warns_unmatched_wildcards() -> None:
    with pytest.raises(NamePatternError, match="引用了未注册名称"):
        resolve_names(_TOOLS, ("aur.test.missing",), label="agent-x")

    handler = _RecordingHandler()
    logger = logging.getLogger("src.utils.patterns")
    logger.addHandler(handler)
    try:
        resolved = resolve_names(_TOOLS, ("aur.mcp.org.aurora.wx.*",))
    finally:
        logger.removeHandler(handler)

    assert resolved == frozenset()
    assert any("未匹配任何已注册名称" in message for message in handler.messages)


def test_pattern_matches_and_rejects_invalid_patterns() -> None:
    assert pattern_matches("aur.**", "aur.a.b.c")
    assert not pattern_matches("aur.serv.world.*", "aur.serv.world.read.deep")

    with pytest.raises(NamePatternError, match="不能为空"):
        resolve_names(_TOOLS, ("",))
    with pytest.raises(NamePatternError, match="不能为空"):
        resolve_names(_TOOLS, ("!",))
    with pytest.raises(NamePatternError, match="未闭合"):
        resolve_names(_TOOLS, ("aur.[a-z.read",))
    with pytest.raises(NamePatternError, match="范围无效"):
        resolve_names(_TOOLS, ("aur.[z-a].*",))
    with pytest.raises(NamePatternError, match="嵌套"):
        resolve_names(_TOOLS, ("aur.[[a].*",))
