from __future__ import annotations

from src.utils import extract_json_from_text


def test_extract_json_from_text_handles_fences_multiline_and_invalid_content() -> None:
    assert extract_json_from_text('Result:\n```json\n{"ok": true}\n```') == {"ok": True}
    assert extract_json_from_text('{"text": "first\nsecond"}') == {"text": "first\nsecond"}
    assert extract_json_from_text("not structured") is None
