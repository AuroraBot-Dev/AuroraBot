"""为结构化数据生成可流式计算、与文件排版无关的内容指纹。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime


class _DataEncoder(json.JSONEncoder):
    """逐层读取声明字段，避免为指纹深复制整份数据集。"""

    def default(self, o: object) -> object:
        """仅接受结构化值、明确时区和映射，不隐式序列化任意对象。"""
        if is_dataclass(o) and not isinstance(o, type):
            return {field.name: getattr(o, field.name) for field in fields(o)}
        if isinstance(o, datetime):
            if o.tzinfo is None or o.utcoffset() is None:
                raise ValueError("数据指纹中的时间必须包含时区")
            return o.astimezone(UTC).isoformat()
        if isinstance(o, Mapping):
            return dict(o)
        return super().default(o)


def data_fingerprint(value: object, *, schema: str) -> str:
    """模式身份参与摘要，样本顺序、字段和监督标签都不能被忽略。"""
    digest = hashlib.sha256((schema + "\n").encode("utf-8"))
    encoder = _DataEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(value):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()
