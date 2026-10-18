"""以资源身份和内容摘要寻址的不可变大对象。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.contracts.resource import ResourceRef

_SHA256 = re.compile(r"[0-9a-f]{64}")
_FIRST_PRINTABLE = 32
DEFAULT_ARTIFACT_CHUNK = 64 * 1024
MAX_ARTIFACT_CHUNK = 1024 * 1024


class ArtifactIntegrityError(ValueError):
    """资源绑定或内容已经损坏，不能作为可信输入返回。"""


def artifact_revision(ref: ResourceRef) -> str:
    """大对象读取必须固定到确切内容版本，不能隐式选择最新文件。"""
    if ref.revision is None or _SHA256.fullmatch(ref.revision) is None:
        raise ValueError("内容资源必须指定 SHA256 版本")
    return ref.revision


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    """逻辑资源版本的内容大小和媒体类型，不公开后端文件路径。"""

    ref: ResourceRef
    size: int
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        """内容身份与描述必须能稳定跨重启恢复。"""
        artifact_revision(self.ref)
        if type(self.size) is not int or self.size < 0:
            raise ValueError("资源内容大小必须是非负整数")
        if (
            not isinstance(self.media_type, str)
            or not self.media_type.strip()
            or any(ord(char) < _FIRST_PRINTABLE for char in self.media_type)
        ):
            raise ValueError("资源媒体类型必须是非空单行文本")


@dataclass(frozen=True, slots=True)
class ArtifactChunk:
    """有界读取的原始字节，位置按字节计算。"""

    info: ArtifactInfo
    offset: int
    content: bytes

    def __post_init__(self) -> None:
        """读取不能越过资源边界，返回的字节保持不可变。"""
        if not isinstance(self.content, bytes):
            raise TypeError("资源内容块必须使用 bytes")
        if type(self.offset) is not int or not 0 <= self.offset <= self.offset + len(self.content) <= self.info.size:
            raise ValueError("资源内容块超出实际内容范围")

    @property
    def next_offset(self) -> int:
        """下一页从本页实际返回的末尾继续。"""
        return self.offset + len(self.content)

    @property
    def has_more(self) -> bool:
        """内容未读完时，调用方可按同一版本继续。"""
        return self.next_offset < self.info.size
