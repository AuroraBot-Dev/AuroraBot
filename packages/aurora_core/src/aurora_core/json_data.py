"""快照与结构化存储共用的严格 JSON 编解码。"""

import json
import math


def _validate_json(value: object, ancestors: set[int] | None = None) -> None:
    """仅接收可无损往返的 JSON 数据类型，拒绝对象、元组、非字符串键和循环。"""
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("JSON 字符串必须可编码为 UTF-8") from None
        return
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON 不支持非有限浮点数")
        return
    if not isinstance(value, (list, dict)) or type(value) not in (list, dict):
        raise TypeError(f"JSON 不支持的数据类型：{type(value).__name__}")
    if ancestors is None:
        ancestors = set()
    if id(value) in ancestors:
        raise ValueError("JSON 不支持循环引用")
    ancestors.add(id(value))
    try:
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise TypeError("JSON 对象的键必须为字符串")
            for key in value:
                _validate_json(key)
            items = value.values()
        else:
            items = value
        for item in items:
            _validate_json(item, ancestors)
    finally:
        ancestors.remove(id(value))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 字段重复：{key}")
        result[key] = value
    return result


def encode_json(value: object, *, indent: int | None = None) -> str:
    """编码可无损往返的 JSON 数据，拒绝运行时对象和隐式类型转换。"""
    _validate_json(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=indent)


def decode_json(content: str) -> object:
    """解码并拒绝重复字段、非有限数及不能编码为 UTF-8 的字符串。"""
    value = json.loads(content, object_pairs_hook=_unique_object)
    _validate_json(value)
    return value
