from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest
from loguru import logger as _loguru_logger

from aurora.utils.platform import detect_os, is_linux, is_macos, is_windows
from aurora.utils.project import get_git_revision
from aurora.utils.table import render_table
from aurorabot.utils import (
    NamePatternError,
    UnsupportedLoggingLevelError,
    bounded_summary,
    configure_console_logging,
    configure_logging,
    console_logging_status,
    extract_json_from_text,
    freeze_json,
    get_logger,
    pattern_matches,
    resolve_names,
    thaw_json,
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
    assert extract_json_from_text("") is None
    assert extract_json_from_text("   ") is None
    assert datetime.fromisoformat(utc_now()).tzinfo is not None
    assert date.fromisoformat(utc_today()) <= datetime.now(UTC).date()


def test_json_roundtrip_freezes_and_thaws_nested_containers() -> None:
    value = {"outer": [1, {"inner": 2}], "flag": True, "text": "x"}
    frozen = cast("MappingProxyType[str, object]", freeze_json(value))
    outer = cast("tuple[object, ...]", frozen["outer"])

    assert isinstance(outer[1], MappingProxyType)
    with pytest.raises(TypeError):
        cast("list[object]", outer)[0] = 9
    with pytest.raises(TypeError):
        cast("dict[str, object]", frozen)["flag"] = False

    thawed = cast("dict[str, object]", thaw_json(frozen))
    assert thawed == value
    assert isinstance(cast("list[object]", thawed["outer"])[1], dict)


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


def test_logging_rejects_unknown_level() -> None:
    with pytest.raises(UnsupportedLoggingLevelError):
        configure_logging("NOT_A_LEVEL")


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


def test_platform_detection_maps_known_and_unknown_systems(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        ("win32", "Windows", (False, False, True)),
        ("darwin", "macOS", (False, True, False)),
        ("linux", "Linux", (True, False, False)),
    ]
    for platform_value, expected_name, flags in cases:
        monkeypatch.setattr("sys.platform", platform_value)
        assert detect_os() == expected_name
        assert (is_linux(), is_macos(), is_windows()) == flags

    monkeypatch.setattr("sys.platform", "freebsd")
    assert detect_os() == "freebsd"


def test_render_table_builds_bordered_columns_and_validates_shape() -> None:
    assert render_table(("Name", "Path"), [("runtime", "config/runtime.toml")]) == (
        "+---------+---------------------+\n"
        "| Name    | Path                |\n"
        "|=========+=====================|\n"
        "| runtime | config/runtime.toml |\n"
        "+---------+---------------------+"
    )
    assert render_table(("A",), [("1",)], banner=("Title",)) == (
        "+-------+\n| Title |\n+-------+\n| A     |\n|=======|\n| 1     |\n+-------+"
    )

    assert render_table(("项目", "内容"), [("系统", "windows")]) == (
        "+------+---------+\n| 项目 | 内容    |\n|======+=========|\n| 系统 | windows |\n+------+---------+"
    )

    with pytest.raises(ValueError, match="列数"):
        render_table(("A", "B"), [("1",)])
    with pytest.raises(ValueError, match="列数"):
        render_table(("A",), [], banner=("x", "y"))


def test_get_git_revision_returns_short_hash_or_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 0
        stdout = "abc1234\n"

    def fake_run(_command: object, **_kwargs: object) -> Result:
        return Result()

    monkeypatch.setattr("aurora.utils.project.subprocess.run", fake_run)
    assert get_git_revision(tmp_path) == "abc1234"

    class FailedResult:
        returncode = 128
        stdout = ""

    monkeypatch.setattr("aurora.utils.project.subprocess.run", lambda *_a, **_k: FailedResult())
    assert get_git_revision(tmp_path) is None

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr("aurora.utils.project.subprocess.run", interrupted)
    assert get_git_revision(tmp_path) is None
