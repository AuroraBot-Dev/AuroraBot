"""长期 Token 的安全文件持久化：原子写入与最小权限。"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from auth.token import generate_token

if TYPE_CHECKING:
    from collections.abc import Callable


class TokenFile:
    """把一个长期 Token 安全持久化到文件；不存在时生成并返回。"""

    def __init__(self, path: Path, *, token_factory: Callable[[], str] = generate_token) -> None:
        self._path = path
        self._token_factory = token_factory

    @property
    def path(self) -> Path:
        return self._path

    def load_or_create(self) -> tuple[str, bool]:
        """返回 ``(token, created)``；created 表示本次新建了文件。"""
        try:
            token = self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            token = ""
        if token:
            _restrict(self._path)
            return token, False

        token = self._token_factory()
        if not token:
            raise RuntimeError("无法生成 Token")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".Token.", suffix=".tmp", dir=self._path.parent)
        temporary_path = Path(temporary_name)
        try:
            _restrict(temporary_path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                descriptor = -1
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(self._path)
            _restrict(self._path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
        return token, True


def _restrict(path: Path) -> None:
    with suppress(OSError):
        path.chmod(0o600)
