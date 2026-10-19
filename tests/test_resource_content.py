"""正文贡献在启动前固定内容与身份，不能凭空声明不可读取的版本。"""

import hashlib
from typing import cast

import pytest

from src.contracts.resource import ResourceKey, ResourceRef
from src.contracts.resource_content import ResourceContent

_KEY = ResourceKey.parse("lab:document/text/notes")
_CONTENT = "实验记录".encode()
_REVISION = hashlib.sha256(_CONTENT).hexdigest()


@pytest.mark.parametrize(
    "revision,content,media_type,error",
    [
        (None, _CONTENT, "text/plain", ValueError),
        ("unresolved", _CONTENT, "text/plain", ValueError),
        ("0" * 64, _CONTENT, "text/plain", ValueError),
        (_REVISION, bytearray(_CONTENT), "text/plain", TypeError),
        (_REVISION, _CONTENT, "text/plain\n", ValueError),
    ],
)
def test_resource_body_rejects_unreliable_publication(
    revision: str | None, content: bytes | bytearray, media_type: str, error: type[Exception]
) -> None:
    """未固定或伪造的摘要、可变字节及无效媒体类型都在构造阶段失败。"""
    with pytest.raises(error):
        ResourceContent(ResourceRef(_KEY, revision), cast("bytes", content), media_type)
