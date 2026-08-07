from __future__ import annotations

from typing import TYPE_CHECKING

from src.utils import (
    atomic_write_json,
    extract_json_from_text,
    parse_structured,
    read_json,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_atomic_json_round_trip_is_sorted_and_cleans_temporary_files(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "record.json"

    atomic_write_json(path, {"z": 1, "a": [True, None]})

    assert read_json(path) == {"a": [True, None], "z": 1}
    assert path.read_text(encoding="utf-8") == '{\n  "a": [\n    true,\n    null\n  ],\n  "z": 1\n}\n'
    assert not list(path.parent.glob(".record.json.*.tmp"))


def test_structured_text_helpers_parse_expected_formats_and_reject_invalid_content() -> None:
    assert extract_json_from_text('Result:\n```json\n{"ok": true}\n```') == {"ok": True}
    assert extract_json_from_text('{"text": "first\nsecond"}') == {"text": "first\nsecond"}
    assert extract_json_from_text("not structured") is None
    assert parse_structured('{"answer": 42}') == {"answer": 42}
    assert parse_structured("enabled: true") == {"enabled": True}
    assert parse_structured('title = "test"') == {"title": "test"}
    assert parse_structured("[") == {}
