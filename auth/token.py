"""Token 生成、恒定时间校验与摘要；不依赖任何应用层。"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_TOKEN_BYTES = 32


def generate_token(*, nbytes: int = _TOKEN_BYTES) -> str:
    """生成 URL-safe 随机 Token。"""
    if nbytes <= 0:
        raise ValueError("nbytes 必须为正")
    return secrets.token_urlsafe(nbytes)


def verify_token(candidate: str | None, expected: str) -> bool:
    """恒定时间比较候选 Token 与期望 Token；空值一律不匹配。"""
    if not candidate or not expected:
        return False
    return hmac.compare_digest(candidate, expected)


def digest_token(token: str) -> str:
    """返回 Token 的 SHA-256 十六进制摘要，用于只存摘要的场景。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
