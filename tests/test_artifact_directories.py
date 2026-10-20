"""并发创建目录时只依据同一次文件状态，不把刚出现的目录误判为文件。"""

from __future__ import annotations

from pathlib import Path

import pytest

from aurorabot.artifacts.files import ensure_directory
from aurorabot.contracts.artifact import ArtifactIntegrityError


def test_directory_created_between_status_lookups_remains_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模拟查询报告此前缺失后，另一发布者立即创建目录的真实交错。"""
    directory = tmp_path / "shared"
    actual_stat = Path.stat

    def lookup(path: Path, *, follow_symlinks: bool = True):
        """查找结果仍描述查询瞬间，创建可以发生在结果被消费之前。"""
        try:
            return actual_stat(path, follow_symlinks=follow_symlinks)
        except FileNotFoundError:
            if path == directory and follow_symlinks:
                path.mkdir()
            raise

    monkeypatch.setattr(Path, "stat", lookup)
    ensure_directory(directory)
    assert directory.is_dir()


def test_another_publisher_can_win_the_atomic_mkdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """原子创建遇到并发胜出者后重新核对目录，保留对文件占用的拒绝。"""
    directory = tmp_path / "shared"
    actual_mkdir = Path.mkdir

    def mkdir(path: Path, mode: int = 0o777, *, parents: bool = False, exist_ok: bool = False) -> None:
        """另一发布者先完成，此调用收到标准的已存在异常。"""
        if path == directory:
            actual_mkdir(path)
            raise FileExistsError("另一发布者已创建")
        actual_mkdir(path, mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    ensure_directory(directory)
    assert directory.is_dir()
    occupied = tmp_path / "occupied"
    occupied.write_bytes(b"not a directory")
    with pytest.raises(ArtifactIntegrityError, match="文件占用"):
        ensure_directory(occupied)
