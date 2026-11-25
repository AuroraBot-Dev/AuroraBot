"""将 QQ 世界事件的图片投影为模型内容，保留原始引导和来源关联。"""

from collections.abc import Iterable
from typing import cast

from aurora_adapter.model import ContentPart, JsonValue
from aurora_adapter.model.content import MAX_CONTENT_PARTS, validate_content
from aurora_core.json_data import encode_json
from aurora_world import WorldRecord


def model_guidance(guidance: object, records: Iterable[WorldRecord]) -> JsonValue:
    """仅识别 QQ 消息段；不下载文件、不读取本地路径、不改写归档或旧引导。"""
    parts: list[ContentPart] = [{"type": "text", "text": encode_json(guidance)}]
    skipped = []
    for record in records:
        event = record.payload
        if isinstance(event, dict) and event.get("kind") == "mcp.event":
            event = event.get("payload")
        if not isinstance(event, dict) or event.get("kind") not in ("qq.message.private", "qq.message.group"):
            continue
        data = event.get("data")
        raw = data.get("onebot") if isinstance(data, dict) else None
        if not isinstance(raw, dict) or raw.get("post_type") != "message":
            continue
        segments = raw.get("message")
        if not isinstance(segments, list):
            continue
        origin = {
            "source_id": record.source_id,
            "record_id": record.record_id,
            "message_id": record.message_id,
            "scope": event.get("scope"),
            "onebot_message_id": raw.get("message_id"),
        }
        unavailable = limited = 0
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict) or segment.get("type") != "image":
                continue
            source = segment.get("data")
            image: ContentPart | None = None
            if isinstance(source, dict):
                for value in (source.get("url"), source.get("file")):
                    candidate = {"type": "image_url", "image_url": {"url": value}}
                    try:
                        validate_content([candidate])
                    except (ValueError, TypeError):
                        continue
                    image = cast(ContentPart, candidate)
                    break
            if image is None:
                unavailable += 1
                continue
            if len(parts) + 2 > MAX_CONTENT_PARTS - 1:
                limited += 1
                continue
            label: ContentPart = {
                "type": "text",
                "text": encode_json({"kind": "world_image", **origin, "segment_index": index}),
            }
            try:
                validate_content([*parts, label, image])
            except ValueError:
                limited += 1
                continue
            parts.extend((label, image))
        if unavailable or limited:
            skipped.append({**origin, "unavailable": unavailable, "over_budget": limited})
    if skipped:
        parts.append(
            {
                "type": "text",
                "text": encode_json(
                    {
                        "kind": "world_image_notice",
                        "notice": (
                            "部分图片未作为视觉输入发送。unavailable 表示缺少有效 HTTPS URL 或图片 data URI，"
                            "over_budget 表示超过内容块或内嵌文件总量限制；不能声称已看到这些图片。"
                        ),
                        "records": skipped,
                    }
                ),
            }
        )
    if len(parts) == 1:
        return cast(JsonValue, guidance)
    return cast(JsonValue, {"kind": "model_input", "content": parts})
