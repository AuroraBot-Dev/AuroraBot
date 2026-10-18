"""不同资源提供者共用的排序与无状态续页规则。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.contracts.resource import ResourceRef
    from src.contracts.resource_query import ResourceQuery

_DIGEST_LENGTH = 64
_CURSOR_VERSION = 2
_MAX_TOKEN_BYTES = 1536

type ResourcePosition = tuple[str, str]


def resource_order(ref: ResourceRef) -> ResourcePosition:
    """使用身份与版本摘要排序，长名称和非内容版本也产生固定长度位置。"""
    if ref.revision is None:
        raise ValueError("资源分页必须使用确定版本")
    return _digest(str(ref.key)), _digest(ref.revision)


def resource_cursor(query: ResourceQuery, last: ResourceRef) -> str:
    """游标绑定筛选条件与最后版本，不引用进程内状态或存储路径。"""
    raw = json.dumps([_CURSOR_VERSION, _filters_digest(query), resource_order(last)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def resource_position(query: ResourceQuery) -> ResourcePosition | None:
    """拒绝跨筛选或损坏游标，允许在继续查询时调整页大小。"""
    if query.after is None:
        return None
    try:
        raw = base64.b64decode(query.after, altchars=b"-_", validate=True)
        if len(raw) > _MAX_TOKEN_BYTES:
            raise ValueError("资源游标超出上限")
        version, filters, position = json.loads(raw)
        if type(version) is not int or version != _CURSOR_VERSION or filters != _filters_digest(query):
            raise ValueError("资源游标与筛选条件不一致")
        identity, revision = position
        for value in (identity, revision):
            if (
                not isinstance(value, str)
                or len(value) != _DIGEST_LENGTH
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError("资源游标身份无效")
        return identity, revision
    except (ValueError, TypeError, binascii.Error) as error:
        raise ValueError("资源分页游标无效或不属于当前筛选") from error


def _digest(value: str) -> str:
    """以统一 UTF-8 编码计算排序摘要。"""
    return hashlib.sha256(value.encode()).hexdigest()


def _filters_digest(query: ResourceQuery) -> str:
    """筛选条件的固定长度指纹不会使长名称扩张游标。"""
    return _digest(json.dumps(query.filters, separators=(",", ":")))
