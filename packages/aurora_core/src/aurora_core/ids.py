"""公共定义 ID 的格式与组成。"""

import re
from dataclasses import dataclass
from typing import override

_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
_NAMESPACE = rf"{_SEGMENT}(?:\.{_SEGMENT})+"
_ID_PATTERN = re.compile(rf"(?P<namespace>{_NAMESPACE}):(?P<domain>{_SEGMENT})/(?P<path>{_SEGMENT}(?:/{_SEGMENT})*)")


def validate_namespace(value: str) -> str:
    """校验定义归属名称；与公共 ID 共用命名空间语法。"""
    if not isinstance(value, str) or re.fullmatch(_NAMESPACE, value) is None:
        raise ValueError(f"无效的命名空间：{value!r}")
    return value


@dataclass(frozen=True)
class Id:
    """定义身份；不包含实例、文件位置或权限信息。"""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _ID_PATTERN.fullmatch(self.value) is None:
            raise ValueError(f"无效的公共 ID：{self.value!r}")

    @property
    def namespace(self) -> str:
        return self.value.split(":", 1)[0]

    @property
    def domain(self) -> str:
        return self.value.split(":", 1)[1].split("/", 1)[0]

    @property
    def local_path(self) -> str:
        return self.value.split("/", 1)[1]

    @override
    def __str__(self) -> str:
        return self.value
