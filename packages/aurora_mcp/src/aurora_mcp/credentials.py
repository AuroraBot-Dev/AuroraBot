"""MCP 凭证引用的声明校验与运行期展开；不保存解析值。"""

import re
from collections.abc import Callable

_REFERENCE = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_|~0-9A-Za-z-]+$")
_CONTROL_HEADERS = {"accept", "content-type", "host", "content-length", "transfer-encoding", "connection", "upgrade"}
_CREDENTIAL_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key"}
_CREDENTIAL_ENV = re.compile(r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|API_KEY|APIKEY|ACCESS_KEY)$", re.IGNORECASE)


def check_reference(value: str, *, credential: bool = False) -> None:
    if "{env" in _REFERENCE.sub("", value):
        raise ValueError("MCP 环境引用须为 {env:NAME}")
    if credential and not _REFERENCE.search(value):
        raise ValueError("MCP 凭证字段必须使用环境引用")


def resolve_values(values: dict[str, str], resolver: Callable[[str], str | None], *, headers: bool) -> dict[str, str]:
    """仅在创建资源时展开引用；失败只返回字段名，不携带声明或解析值。"""
    result = {}
    for key, value in values.items():

        def replace(match: re.Match) -> str:
            resolved = resolver(match[1])
            if not resolved or not resolved.strip():
                raise ValueError("环境引用不可用")
            return resolved

        try:
            resolved = _REFERENCE.sub(replace, value)
            if "\0" in resolved or (
                headers and (not resolved.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in resolved))
            ):
                raise ValueError(key)
        except Exception:  # noqa: BLE001 — 自定义解析器也不得通过异常泄露凭证。
            raise ValueError(key) from None
        result[key] = resolved
    return result


def check_headers(values: dict[str, str]) -> None:
    """拒绝重复、控制头、非法字符和已知凭证字面量。"""
    seen = set()
    for key, content in values.items():
        lower = key.lower()
        if not _HEADER_NAME.fullmatch(key) or lower in seen or lower in _CONTROL_HEADERS or lower.startswith("mcp-"):
            raise ValueError("MCP headers 名称冲突、非法或由协议管理")
        seen.add(lower)
        check_reference(content, credential=lower in _CREDENTIAL_HEADERS)
        if not content.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in content):
            raise ValueError("MCP headers 值含非法字符")


def check_environment(values: dict[str, str]) -> None:
    """环境凭证使用引用；普通环境值不允许 NUL。"""
    for key, content in values.items():
        check_reference(content, credential=bool(_CREDENTIAL_ENV.search(key)))
        if "\0" in content:
            raise ValueError("MCP environment 含 NUL")
