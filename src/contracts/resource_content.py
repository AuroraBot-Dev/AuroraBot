"""模组贡献的冻结正文，由独立归档模块在后台启动前保存。"""

import hashlib
from dataclasses import dataclass

from src.contracts.artifact import ArtifactInfo
from src.contracts.kernel import ContributionKey
from src.contracts.resource import ResourceRef


@dataclass(frozen=True, slots=True)
class ResourceContent:
    """正文与资源身份一同冻结，贡献方不能声明与字节不符的版本。"""

    ref: ResourceRef
    content: bytes
    media_type: str

    def __post_init__(self) -> None:
        """在装配时核对内容摘要与元信息，避免启动后才发现虚假引用。"""
        if not isinstance(self.content, bytes):
            raise TypeError("资源正文必须是不可变 bytes")
        ArtifactInfo(self.ref, len(self.content), self.media_type)
        if hashlib.sha256(self.content).hexdigest() != self.ref.revision:
            raise ValueError("资源正文与声明版本不一致")


RESOURCE_CONTENTS = ContributionKey[ResourceContent]("aurora:resources/contribution/content")
