"""模型内容的固定版本校验，不依赖具体计算框架。"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from src.contracts.resource import ResourceRef

if TYPE_CHECKING:
    from src.contracts.resource import ResourceKey

MODEL_MEDIA_TYPE = "application/vnd.aurora.model+pt;version=1"


def model_content_ref(content: bytes, key: ResourceKey, expected: ResourceRef | None = None) -> ResourceRef:
    """摘要取自即将解码的同一份字节，指定版本必须精确相等。"""
    if not isinstance(content, bytes):
        raise TypeError("模型内容必须是不可变 bytes")
    actual = ResourceRef(key, hashlib.sha256(content).hexdigest())
    if expected is not None and actual != expected:
        raise ValueError("模型内容与指定资源版本不一致")
    return actual
