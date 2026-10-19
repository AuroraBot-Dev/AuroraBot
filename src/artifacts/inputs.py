"""内容资源操作的结构化输入，独立于存储调用与结果呈现。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.contracts.artifact import MAX_ARTIFACT_CHUNK
from src.contracts.resource import ResourceKey, ResourceRef

_MAX_BASE64 = ((MAX_ARTIFACT_CHUNK + 2) // 3) * 4


class ArtifactInput(BaseModel):
    """读取总是固定到调用方指定的内容摘要。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    key: str
    revision: str = Field(pattern="^[0-9a-f]{64}$")

    @property
    def ref(self) -> ResourceRef:
        """将协议输入转换为规范资源身份。"""
        return ResourceRef(ResourceKey.parse(self.key), self.revision)


class ArtifactReadInput(ArtifactInput):
    """小块字节不会隐式展开成整个文件。"""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=4096, ge=1, le=16384)
    encoding: Literal["base64", "utf-8"] = "base64"


class ArtifactPutInput(BaseModel):
    """结构化写入有界；更大内容由宿主使用流式端口保存。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    key: str
    content_base64: str = Field(max_length=_MAX_BASE64)
    media_type: str = "application/octet-stream"
