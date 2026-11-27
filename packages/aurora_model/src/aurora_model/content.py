"""结构化文件输入校验与预算；不访问远程地址或宿主文件系统。"""

import base64
import binascii
from copy import deepcopy
from typing import cast
from urllib.parse import urlsplit

from aurora_core.json_data import encode_json

from .contract import ChatClient, ChatRequest, MessageContent, ModelProtocolError, UnsupportedCapability

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CONTENT_PARTS = 32


def _source(value: object, *, image: bool = False, file_id: bool = False) -> int:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("文件来源须为非空字符串")
    if value.startswith("data:"):
        if file_id:
            raise ValueError("内嵌文件须使用 file_data，不能作为 file_id")
        header, separator, data = value.partition(",")
        if not separator or not header.endswith(";base64") or "/" not in header:
            raise ValueError("内嵌文件须使用含 MIME 类型的 base64 data URI")
        if image and not header.startswith("data:image/"):
            raise ValueError("图片须使用 image MIME 类型")
        if len(data) > 4 * ((MAX_FILE_BYTES + 2) // 3):
            raise ValueError("文件输入不能超过 10 MiB")
        try:
            size = len(base64.b64decode(data, validate=True))
        except (ValueError, binascii.Error):
            raise ValueError("文件 base64 数据无效") from None
        if not 0 < size <= MAX_FILE_BYTES:
            raise ValueError("文件必须非空且不超过 10 MiB")
        return size
    if len(value) > 8192:
        raise ValueError("文件引用过长")
    url = urlsplit(value)
    if url.scheme == "https" and url.hostname and not url.username and not url.password:
        return 0
    if file_id and not url.scheme and not any(char in value for char in ("/", "\\", " ", "\n", "\r")):
        return 0
    raise ValueError("文件须使用 HTTPS URL、data URI 或供应商文件 ID，不接受本地路径")


def validate_content(value: object) -> MessageContent:
    """校验公共消息内容；单条消息的内嵌文件合计最多 10 MiB。"""
    if isinstance(value, str):
        return value
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CONTENT_PARTS:
        raise ValueError("结构化消息须包含 1 至 32 个内容块")
    size = 0
    for part in value:
        if not isinstance(part, dict):
            raise TypeError("内容块须为对象")
        kind = part.get("type")
        if kind == "text":
            if set(part) != {"type", "text"} or not isinstance(part["text"], str):
                raise ValueError("文本内容块无效")
        elif kind == "image_url":
            source = part.get("image_url")
            if (
                set(part) != {"type", "image_url"}
                or not isinstance(source, dict)
                or set(source) - {"url", "detail"}
                or source.get("detail", "auto") not in ("auto", "low", "high")
            ):
                raise ValueError("图片内容块无效")
            size += _source(source.get("url"), image=True)
        elif kind == "file":
            source = part.get("file")
            if (
                set(part) != {"type", "file"}
                or not isinstance(source, dict)
                or set(source) - {"filename", "file_data", "file_id"}
                or ("file_data" in source) == ("file_id" in source)
                or (
                    "filename" in source
                    and (not isinstance(source["filename"], str) or not 1 <= len(source["filename"]) <= 256)
                )
            ):
                raise ValueError("文件内容块无效")
            if "file_data" in source and (
                not isinstance(source["file_data"], str) or not source["file_data"].startswith("data:")
            ):
                raise ValueError("file_data 须为 data URI；远程文件请使用 file_id")
            size += _source(source.get("file_data", source.get("file_id")), file_id="file_id" in source)
        else:
            raise ValueError("不支持的消息内容块")
    if size > MAX_FILE_BYTES:
        raise ValueError("单条消息的文件合计不能超过 10 MiB")
    return cast(MessageContent, value)


def request_size(request: ChatRequest) -> tuple[int, int]:
    """计算文本 JSON 字符与内嵌文件字节；二进制编码不冒充文本 token。"""
    compact = {**request, "messages": [deepcopy(message) for message in request["messages"]]}
    size = 0
    for message in compact["messages"]:
        if isinstance(message["content"], str):
            continue
        message["content"] = [deepcopy(part) for part in message["content"]]
        for part in message["content"]:
            if part["type"] == "text":
                continue
            source = cast(dict, part["image_url"] if part["type"] == "image_url" else part["file"])
            key = "url" if part["type"] == "image_url" else "file_data"
            data = source.get(key, "")
            if data.startswith("data:") and "," in data:
                header, encoded = data.split(",", 1)
                padding = len(encoded) - len(encoded.rstrip("="))
                size += len(encoded) // 4 * 3 - padding
                source[key] = f"{header},[binary]"
    return len(encode_json(compact)), size


def require_capabilities(client: ChatClient, request: ChatRequest, *, streaming: bool) -> None:
    for message in request["messages"]:
        content = validate_content(message["content"])
        if isinstance(content, list) and any(part["type"] != "text" for part in content):
            if message["role"] != "user":
                raise ModelProtocolError("文件输入仅接受 user 消息")
            if not client.capabilities.file_input:
                raise UnsupportedCapability("模型不支持文件输入")
    if streaming and not client.capabilities.streaming:
        raise UnsupportedCapability("模型不支持流式响应")
    uses_tools = request.get("tools") or any(
        message.get("tool_calls") or message["role"] == "tool" for message in request["messages"]
    )
    if uses_tools and not client.capabilities.tool_calls:
        raise UnsupportedCapability("模型不支持工具调用")
