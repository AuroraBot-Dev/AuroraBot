"""将不可变 JSON 对象逐段编码为 UTF-8，不复制整棵容器树。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FrozenEncoder(json.JSONEncoder):
    """标准编码器原生处理元组，映射只在访问到该层时展开。"""

    def default(self, o: object) -> object:
        """不把未知对象悄悄转换成字符串。"""
        if isinstance(o, Mapping):
            return dict(o)
        return super().default(o)


def json_bytes(value: object) -> Iterator[bytes]:
    """保持确定字段顺序和严格数值语义，字符串标量由标准库编码。"""
    encoder = _FrozenEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(value):
        yield chunk.encode("utf-8")
