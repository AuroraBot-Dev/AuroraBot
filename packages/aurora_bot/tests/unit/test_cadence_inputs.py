"""QQ 图片投影保留来源，拒绝不支持的来源并遵守模型内容预算。"""

from copy import deepcopy
from typing import cast

import pytest
from aurora_adapter.model import content as model_content
from aurora_bot.cadence.inputs import model_guidance
from aurora_core.json_data import decode_json
from aurora_world import WorldPosition, WorldRecord


def record(segments, *, wrapped=True):
    event = {
        "kind": "qq.message.private",
        "scope": "qq:private:42",
        "data": {"onebot": {"post_type": "message", "message_id": 123, "message": segments}},
    }
    payload = {"kind": "mcp.event", "payload": event} if wrapped else event
    return WorldRecord(WorldPosition("journal", 1, "record"), "record", "qq/events", "event", payload)


@pytest.mark.parametrize("wrapped", [False, True])
def test_projects_images_in_segment_order_without_mutating_original(wrapped):
    item = record(
        [
            {"type": "text", "data": {"text": "比较两张图"}},
            {"type": "image", "data": {"file": "a.jpg", "url": "https://cdn.example/a.jpg"}},
            {"type": "image", "data": {"file": "data:image/png;base64,eA=="}},
        ],
        wrapped=wrapped,
    )
    before = deepcopy(item.payload)
    result = model_guidance(item.payload, (item,))
    assert isinstance(result, dict) and result["kind"] == "model_input"
    parts = cast(list[dict], result["content"])
    assert isinstance(parts, list)
    assert decode_json(parts[0]["text"]) == before
    assert [part["image_url"]["url"] for part in parts if part["type"] == "image_url"] == [
        "https://cdn.example/a.jpg",
        "data:image/png;base64,eA==",
    ]
    label = decode_json(parts[1]["text"])
    assert label == {
        "kind": "world_image",
        "source_id": "qq/events",
        "record_id": "record",
        "message_id": "event",
        "scope": "qq:private:42",
        "onebot_message_id": 123,
        "segment_index": 1,
    }
    assert item.payload == before


@pytest.mark.parametrize(
    "value", ["file:///secret.png", "http://cdn.example/a.jpg", "a.jpg", "data:image/png;base64,%%", None]
)
def test_invalid_image_does_not_hide_valid_image_or_drop_message(value):
    item = record(
        [
            {"type": "image", "data": {"url": value}},
            {"type": "image", "data": {"url": "https://cdn.example/good.jpg"}},
        ]
    )
    result = model_guidance(item.payload, (item,))
    assert isinstance(result, dict)
    parts = cast(list[dict], result["content"])
    assert isinstance(parts, list)
    model_content.validate_content(parts)
    assert sum(part["type"] == "image_url" for part in parts) == 1
    notice = decode_json(parts[-1]["text"])
    assert notice["records"][0]["unavailable"] == 1


def test_content_limit_reports_omitted_images():
    item = record([{"type": "image", "data": {"url": f"https://cdn.example/{index}.jpg"}} for index in range(20)])
    result = model_guidance(item.payload, (item,))
    assert isinstance(result, dict)
    parts = cast(list[dict], result["content"])
    assert isinstance(parts, list) and len(parts) == model_content.MAX_CONTENT_PARTS
    model_content.validate_content(parts)
    notice = decode_json(parts[-1]["text"])
    assert notice["records"][0]["over_budget"] == 5


def test_binary_limit_is_shared_across_images(monkeypatch):
    monkeypatch.setattr(model_content, "MAX_FILE_BYTES", 3)
    item = record([{"type": "image", "data": {"url": "data:image/png;base64,eHg="}}] * 2)
    result = model_guidance(item.payload, (item,))
    assert isinstance(result, dict)
    parts = cast(list[dict], result["content"])
    assert isinstance(parts, list)
    model_content.validate_content(parts)
    assert sum(part["type"] == "image_url" for part in parts) == 1
    notice = decode_json(parts[-1]["text"])
    assert notice["records"][0]["over_budget"] == 1


@pytest.mark.parametrize(
    "payload", ["文字", {"url": "https://cdn.example/a.jpg"}, {"kind": "model_input", "content": []}]
)
def test_unrelated_payloads_are_not_interpreted_as_images(payload):
    item = WorldRecord(WorldPosition("journal", 1, "record"), "record", "other", "event", payload)
    assert model_guidance(payload, (item,)) is payload
    text = record([{"type": "text", "data": {"text": "你好"}}])
    assert model_guidance(text.payload, (text,)) is text.payload
