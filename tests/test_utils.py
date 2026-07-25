from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from src.utils.serialization import atomic_write_json, extract_json_from_text, json_ready, parse_structured, read_json
from src.utils.time import from_epoch_seconds, now_text, parse_time_value, to_epoch_seconds, to_time_text

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


def test_json_ready_normalizes_nested_dates_tuples_and_keys() -> None:
    value = {1: (date(2024, 1, 2), datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC))}
    assert json_ready(value) == {"1": ["2024-01-02", "2024-01-02T03:04:05+00:00"]}


def test_time_helpers_normalize_iso_text_and_epoch_values() -> None:
    parsed = parse_time_value("1970-01-01T00:00:00Z")
    fallback = 1.5
    epoch = 1_700_000_000
    naive = datetime.fromisoformat("2024-01-02T00:00:00")

    assert parsed is not None and parsed.tzinfo is not None
    assert to_epoch_seconds(parsed) == 0
    assert to_epoch_seconds("invalid", default=fallback) == fallback
    assert to_time_text("invalid") is None
    assert datetime.fromisoformat(to_time_text(parsed) or "").timestamp() == 0
    assert datetime.fromisoformat(from_epoch_seconds(epoch)).timestamp() == epoch
    parsed_naive = parse_time_value(naive)
    assert parsed_naive is not None and parsed_naive.tzinfo is not None
    assert parse_time_value(now_text()) is not None
