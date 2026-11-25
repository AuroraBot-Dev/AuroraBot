"""验证 JSON 字符串可安全写入 UTF-8，并保留合法 Unicode。"""

import json

import pytest
from aurora_core.json_data import decode_json, encode_json


@pytest.mark.parametrize("value", [chr(0xD800), chr(0xDFFF), ["\ud800"], {"text": "\udfff"}, {"\ud800": 1}])
def test_rejects_surrogates_in_values_and_keys(value):
    with pytest.raises(ValueError, match="UTF-8"):
        encode_json(value)
    with pytest.raises(ValueError, match="UTF-8"):
        decode_json(json.dumps(value))


def test_preserves_chinese_and_non_bmp_characters():
    value = {"中文😀": ["内容𠀀", "\u0000"]}
    encoded = encode_json(value)
    assert "中文😀" in encoded
    assert decode_json(encoded.encode("utf-8").decode("utf-8")) == value
    assert decode_json('"\\ud83d\\ude00"') == "😀"
