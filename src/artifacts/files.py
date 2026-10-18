"""原子发布不可变文件，失败时不会暴露半份资源。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from src.contracts.artifact import ArtifactIntegrityError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

_BLOCK_SIZE = 1024 * 1024


def ensure_directory(path: Path) -> None:
    """创建目录并同步父目录，已有内部目录不能被文件或链接替代。"""
    if path.is_symlink():
        raise ArtifactIntegrityError("资源内部目录不能是符号链接")
    if path.is_dir():
        return
    if path.exists():
        raise ArtifactIntegrityError("资源内部目录被其他文件占用")
    ensure_directory(path.parent)
    path.mkdir(exist_ok=True)
    sync_directory(path.parent)


def sync_directory(path: Path) -> None:
    """支持目录同步的平台在发布前确认目录项持久化。"""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage(chunks: Iterable[bytes], temporary: Path) -> tuple[Path, str, int]:
    """流式落盘并计算摘要，异常会清理尚未发布的临时文件。"""
    ensure_directory(temporary)
    digest = hashlib.sha256()
    size = 0
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=temporary, delete=False) as output:
            path = Path(output.name)
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("资源内容流只能产生 bytes")
                digest.update(chunk)
                output.write(chunk)
                size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        return path, digest.hexdigest(), size
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def publish(staged: Path, destination: Path) -> bool:
    """以不可覆盖的原子目录项发布文件，其他发布者先完成时保留原版本。"""
    ensure_directory(destination.parent)
    try:
        os.link(staged, destination)
    except FileExistsError:
        sync_directory(destination.parent)
        return False
    sync_directory(destination.parent)
    return True


def file_chunks(source: Path) -> Iterator[bytes]:
    """导入期间检查同一个打开文件，不能把变动的内容当成稳定快照。"""
    with source.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while chunk := stream.read(_BLOCK_SIZE):
            yield chunk
        after = os.fstat(stream.fileno())
        if signature(before) != signature(after):
            raise ValueError("导入期间源文件发生变化，请固定文件后重试")


def signature(status: os.stat_result) -> tuple[int, int, int, int, int]:
    """检查文件身份与变更信息，完整性缓存不只依赖文件名。"""
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns
