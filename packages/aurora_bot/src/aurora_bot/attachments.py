"""直接交流附件转换；只处理调用方提供的字节，不读取宿主路径。"""

import base64

from aurora_adapter.model import ContentPart, MessageContent
from aurora_adapter.model.content import validate_content

MEDIA_TYPES = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
)


def message_content(text: str, files: object) -> MessageContent:
    if not isinstance(files, list) or len(files) > 8:
        raise ValueError("附件须为列表且最多 8 个")
    if not files:
        if not text.strip():
            raise ValueError("消息和附件不能同时为空")
        return text
    parts: list[ContentPart] = [{"type": "text", "text": text}] if text else []
    for file in files:
        if (
            not isinstance(file, dict)
            or set(file) != {"name", "media_type", "data"}
            or not isinstance(file["name"], str)
            or not 1 <= len(file["name"]) <= 256
            or file["media_type"] not in MEDIA_TYPES
            or not isinstance(file["data"], str)
        ):
            raise ValueError("附件字段或类型无效")
        uri = f"data:{file['media_type']};base64,{file['data']}"
        if file["media_type"].startswith("image/"):
            parts.append({"type": "image_url", "image_url": {"url": uri}})
        else:
            parts.append({"type": "file", "file": {"filename": file["name"], "file_data": uri}})
    validate_content(parts)
    for index, part in enumerate(parts):
        if part["type"] != "file":
            continue
        uri = part["file"]["file_data"]
        if not uri.startswith(("data:text/", "data:application/json;")):
            continue
        try:
            content = base64.b64decode(uri.partition(",")[2], validate=True).decode("utf-8-sig")
        except UnicodeError:
            raise ValueError("文本附件必须使用 UTF-8 编码") from None
        name = part["file"]["filename"]
        parts[index] = {"type": "text", "text": f"附件：{name}\n{content}"}
    return parts
