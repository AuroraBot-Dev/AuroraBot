"""独立 Token 认证包的行为测试。"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from auth import TokenFile, digest_token, generate_token, verify_token

if TYPE_CHECKING:
    from pathlib import Path


def test_generate_token_returns_unique_urlsafe_values() -> None:
    first = generate_token()
    second = generate_token()

    assert first and second and first != second


def test_generate_token_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError, match="nbytes"):
        generate_token(nbytes=0)


def test_verify_token_is_constant_time_and_rejects_empty_values() -> None:
    token = generate_token()

    assert verify_token(token, token) is True
    assert verify_token("wrong", token) is False
    assert verify_token("", token) is False
    assert verify_token(None, token) is False
    assert verify_token(token, "") is False


def test_digest_token_is_stable_sha256() -> None:
    assert digest_token("abc") == hashlib.sha256(b"abc").hexdigest()


def test_token_file_creates_then_reloads(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "Token.txt"
    store = TokenFile(path)

    token, created = store.load_or_create()
    again, created_again = store.load_or_create()

    assert created is True and created_again is False
    assert again == token
    assert path.read_text(encoding="utf-8").strip() == token


def test_token_file_rejects_empty_generated_token(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="无法生成 Token"):
        TokenFile(tmp_path / "Token.txt", token_factory=lambda: "").load_or_create()
