from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from loguru import logger as _loguru_logger

from aurorabot.utils import (
    NamePatternError,
    configure_console_logging,
    configure_logging,
    console_logging_status,
    extract_json_from_text,
    get_logger,
    pattern_matches,
    resolve_names,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_extract_json_escapes_raw_control_characters_inside_strings() -> None:
    assert extract_json_from_text('{"a": "x\ty"}') == {"a": "x\ty"}
    assert extract_json_from_text('{"a": "x\ry"}') == {"a": "x\ry"}
    assert extract_json_from_text('{"a": "x\n\ty"}') == {"a": "x\n\ty"}
    assert extract_json_from_text(r'{"a": "x\y"}') is None


def test_standard_logging_updates_console_and_rotating_file(tmp_path: Path) -> None:
    logfile = tmp_path / "logs" / "aurora.log"
    logger = get_logger("tests.utils.logging")

    configure_logging("INFO", logfile)
    configure_console_logging(enabled=False)
    logger.info("日志已写入")

    assert "日志已写入" in logfile.read_text(encoding="utf-8")
    assert console_logging_status() == {
        "enabled": False,
        "console_level": "info",
        "file_level": "info",
    }
    configure_console_logging(enabled=True, level=logging.WARNING)
    assert console_logging_status()["console_level"] == "warning"


_TOOLS = frozenset(
    {
        "aurora:tool/definition/delegate",
        "org.aurora.qq:tool/definition/qq_send_private_message",
        "org.aurora.qq:tool/definition/qq_send_group_message",
        "org.aurora.clock:tool/definition/get_current_time",
        "aurora:tool/definition/world_read",
        "aurora:tool/definition/world_trees",
    }
)


def test_resolve_names_applies_ordered_patterns_with_last_match_wins() -> None:
    """按顺序决定可见性；无冒号模式匹配命名空间前缀，双星号可跨层。"""
    assert resolve_names(_TOOLS, ("aurora:tool/definition/delegate", "aurora:tool/definition/world_*")) == frozenset(
        {"aurora:tool/definition/delegate", "aurora:tool/definition/world_read", "aurora:tool/definition/world_trees"}
    )
    assert resolve_names(
        _TOOLS, ("org.aurora.qq:tool/definition/*", "!org.aurora.qq:tool/definition/qq_send_group_message")
    ) == (frozenset({"org.aurora.qq:tool/definition/qq_send_private_message"}))
    assert resolve_names(_TOOLS, ("!org.aurora.qq:tool/definition/*",)) == frozenset()
    assert resolve_names(_TOOLS, ("org.aurora.**",)) == frozenset(
        {
            "org.aurora.qq:tool/definition/qq_send_private_message",
            "org.aurora.qq:tool/definition/qq_send_group_message",
            "org.aurora.clock:tool/definition/get_current_time",
        }
    )
    assert resolve_names(_TOOLS, ("org.aurora.qq:tool/definition/qq_send_*_message",)) == frozenset(
        {"org.aurora.qq:tool/definition/qq_send_private_message", "org.aurora.qq:tool/definition/qq_send_group_message"}
    )
    assert resolve_names(_TOOLS, ("org.aurora.qq:tool/definition/qq_send_?rivate_message",)) == frozenset(
        {"org.aurora.qq:tool/definition/qq_send_private_message"}
    )
    assert resolve_names(_TOOLS, ("org.aurora.qq:tool/definition/qq_send_[gp]rivate_message",)) == frozenset(
        {"org.aurora.qq:tool/definition/qq_send_private_message"}
    )
    assert resolve_names(_TOOLS, ("*:tool/definition/*",)) == frozenset(
        {"aurora:tool/definition/delegate", "aurora:tool/definition/world_read", "aurora:tool/definition/world_trees"}
    )
    assert resolve_names(_TOOLS, ()) == frozenset()


def test_resolve_names_rejects_unmatched_exact_and_warns_unmatched_wildcards() -> None:
    with pytest.raises(NamePatternError, match="引用了未注册名称"):
        resolve_names(_TOOLS, ("test:tool/definition/missing",), label="agent-x")

    captured: list[str] = []
    sink_id = _loguru_logger.add(captured.append, format="{message}")
    try:
        resolved = resolve_names(_TOOLS, ("org.aurora.wx:tool/definition/*",))
    finally:
        _loguru_logger.remove(sink_id)

    assert resolved == frozenset()
    assert any("未匹配任何已注册名称" in message for message in captured)


def test_pattern_matches_and_rejects_invalid_patterns() -> None:
    assert pattern_matches("org.aurora.**", "org.aurora.qq:tool/definition/qq_send_private_message")
    assert not pattern_matches("aurora:tool/definition/*", "aurora:tool/definition/room/read")

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


def test_wildcard_reach_follows_the_id_level_syntax() -> None:
    """单星号遵守命名空间与路径层级，路径中的点和业务域的冒号均为普通字符。"""
    assert pattern_matches("org.aurora.qq:tool/definition/*", "org.aurora.qq:tool/definition/send.message")
    assert pattern_matches("aurora:tool/definition/world_*", "aurora:tool/definition/world_read.deep")
    assert not pattern_matches("org.aurora.qq:tool/definition/*", "org.aurora.qq:tool/definition/room/send")
    assert pattern_matches("org.aurora.qq:tool/definition/**", "org.aurora.qq:tool/definition/room/send")
    assert not pattern_matches("*:tool/definition/*", "org.aurora.qq:tool/definition/send")
    assert pattern_matches("**:tool/definition/*", "org.aurora.qq:tool/definition/send")
    assert pattern_matches("qq:*", "qq:group:123")
