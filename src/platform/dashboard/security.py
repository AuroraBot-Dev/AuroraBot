"""不依赖框架的不透明 bearer-token 原语。"""

from __future__ import annotations

import hashlib
import secrets


def new_token() -> str:
    """生成一个 URL 安全的随机 token 字符串。"""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """计算 token 的 SHA-256 摘要，用于安全存储。"""
    return hashlib.sha256(token.encode()).hexdigest()
