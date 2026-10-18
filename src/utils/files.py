"""将完整字节作为新文件原子发布，已有内容不能被意外覆盖。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_new_file(path: Path, content: bytes) -> None:
    """先同步临时内容，再发布不可覆盖的目录项，失败时清理临时文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            staged = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staged, path)
        except FileExistsError as error:
            raise FileExistsError(f"目标文件已经存在：{path}") from error
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
